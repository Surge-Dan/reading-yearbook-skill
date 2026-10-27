"""End-to-end HTML delivery; credentials stay in the assistant environment.

Use a supplied snapshot to reuse verified records, or collect annual/shelf data.
Only probe additional year candidates when the annual book count is not covered.
Successful empty notebooks are valid; incomplete collection stays explicit.
"""
import argparse
import hashlib
import json
import os
import re
import threading
from datetime import datetime
from pathlib import Path

from build_reading_html import TZ, adapt_data, build_html, date_value, merge_annual, merge_materials
from collect_html_materials import call, collect, cached_response, cache_expired, reuse_previous_materials
from collect_weread_data import WeReadError, select_candidate_books
from html_contract import atomic_json


class ScopeRequired(WeReadError):
    def __init__(self, snapshot, candidates):
        super().__init__('年度汇总已取得；继续扩查需要确认请求范围', 'budget')
        self.snapshot = snapshot
        self.candidates = candidates


def annual_data(snapshot):
    year=int(snapshot['year'])
    data=adapt_data({'year':year,'as_of':snapshot.get('as_of'),'source_mode':'live',
                     'verification_status':'live_verified','summary':{},'books':[]})
    merge_annual(data,snapshot)
    if not any(row.get('stat')=='读过' and re.fullmatch(r'\s*\d+\s*(?:本)?\s*',str(row.get('counts'))) for row in snapshot.get('annual',{}).get('readStat',[])):
        data['summary']['read']=None
        data['coverage']['annual_books']=None
        data['coverage']['complete']=False
    # Share a small set initially; every book still belongs in the full shelf.
    for book in data['books'][:4]:
        book['selected']=True
    return data


def cache_directory(base, key, year):
    """Separate authorizations and dates without storing the credential."""
    owner=hashlib.sha256(key.encode()).hexdigest()[:20]
    return Path(base)/owner/str(year)/datetime.now(TZ).strftime('%Y-%m-%d')


def collect_snapshot(year, key, cache, refresh=False, allow_large=False, request_budget=100):
    cache=Path(cache);cache.mkdir(parents=True,exist_ok=True)
    raw=cache/'raw';raw.mkdir(exist_ok=True)
    stopped=threading.Event()
    def request(api,params,path):
        return call(api,params,key,path,stopped,refresh=refresh)
    shelf=request('/shelf/sync',{},raw/'shelf.json')
    annual=request('/readdata/detail',{'mode':'annually','baseTime':int(datetime(year,1,1,tzinfo=TZ).timestamp())},raw/'annual.json')
    if not isinstance(shelf.get('books'),list) or not isinstance(annual.get('readStat'),list):
        raise WeReadError('年度或书架响应结构不完整，不能据此生成完整年鉴')
    snapshot={'year':year,'as_of':datetime.now(TZ).strftime('%Y-%m-%d'),'shelf':shelf,'annual':annual,'non_ranked_progress':[],'errors':[]}
    for scope,reply in [('shelf',shelf),('annual',annual)]:
        if reply.get('_cache_status')=='stale':snapshot['errors'].append({'scope':scope,'message':'刷新失败，保留上次数据'})
    data=annual_data(snapshot)
    if not data['coverage']['complete']:
        used=0;scope_candidates=len(shelf.get('books',[]))
        def budgeted(api,params,path):
            nonlocal used
            if refresh or cached_response(api,path) is None or cache_expired(path):
                if used>=request_budget and not allow_large:
                    snapshot['discovery_incomplete']=True
                    snapshot['discovery_requests']=used
                    atomic_json(cache/'annual-snapshot.json',snapshot)
                    raise ScopeRequired(snapshot,scope_candidates)
                used+=1
            return request(api,params,path)
        notebook_books=[];cursor=None;seen=set()
        for page_index in range(20):
            page=budgeted('/user/notebooks',{'count':50,'lastSort':cursor},raw/f'notebooks-{page_index}.json')
            if page.get('_cache_status')=='stale':snapshot['errors'].append({'scope':'notebooks','message':'刷新失败，保留上次笔记本'})
            rows=page.get('books')
            if not isinstance(rows,list):raise WeReadError('笔记本响应结构不完整')
            notebook_books.extend(rows)
            if not page.get('hasMore'):break
            next_cursor=rows[-1].get('sort') if rows else None
            if next_cursor is None or next_cursor in seen:
                snapshot['errors'].append({'scope':'notebooks','message':'笔记本分页未完成'});break
            seen.add(next_cursor);cursor=next_cursor
        else:snapshot['errors'].append({'scope':'notebooks','message':'笔记本分页达到本轮上限'})
        notebooks={'books':notebook_books}
        # Discovery hints require verified year progress before adding books.
        known={book['book_id'] for book in data['books']}
        historical=year<datetime.now(TZ).year
        candidates=select_candidate_books(year,shelf,notebooks,annual,scan_all=historical)
        pending=[b for b in candidates if str(b.get('bookId') or '') not in known]
        scope_candidates=len(pending)
        if len(pending)>100 and not allow_large:
            snapshot['discovery_incomplete']=True
            atomic_json(cache/'annual-snapshot.json',snapshot)
            raise ScopeRequired(snapshot,len(pending))
        for book in pending:
            book_id=str(book.get('bookId') or '')
            if book_id in known:continue
            safe=hashlib.sha256(book_id.encode()).hexdigest()[:20]
            try:
                reply=budgeted('/book/getprogress',{'bookId':book_id},raw/f'{safe}-progress.json')
                progress=reply.get('book') or {}
                last=date_value(progress.get('updateTime') or book.get('readUpdateTime'))
                started=bool(progress.get('isStartReading') or progress.get('progress') or progress.get('recordReadingTime'))
                if reply.get('_cache_status')=='stale':snapshot['errors'].append({'book_id':book_id,'scope':'progress','message':'刷新失败，保留上次进度'})
                year_note=False
                if historical and (not last or int(last[:4])!=year):
                    marks=budgeted('/book/bookmarklist',{'bookId':book_id},raw/f'{safe}-highlights.json')
                    year_note=any((d:=date_value(n.get('createTime'))) and int(d[:4])==year for n in marks.get('updated',[]))
                    if not year_note:
                        # Reserve the bounded pagination budget before expanding personal notes.
                        thought_seen={0}
                        for page_index in range(20):
                            params={'bookid':book_id,'count':50,'synckey':0 if page_index==0 else cursor}
                            thought=budgeted('/review/list/mine',params,raw/f'{safe}-discovery-thoughts-{page_index}.json')
                            year_note=any((d:=date_value((n.get('review') or n).get('createTime'))) and int(d[:4])==year for n in thought.get('reviews',[]))
                            if year_note or not thought.get('hasMore'): break
                            next_cursor=thought.get('synckey')
                            if next_cursor is None or next_cursor in thought_seen:
                                snapshot['errors'].append({'book_id':book_id,'scope':'thoughts','message':'历史笔记分页未完成'});break
                            thought_seen.add(next_cursor);cursor=next_cursor
                        else:snapshot['errors'].append({'book_id':book_id,'scope':'thoughts','message':'历史笔记分页超过上限'})
                snapshot['non_ranked_progress'].append({'book_id':book_id,'title':book.get('title'),
                    'last_read':last,'is_started':started,'progress':progress.get('progress'),'year_note_evidence':year_note,'finished_on':date_value(progress.get('finishTime'))})
            except ScopeRequired:
                raise
            except WeReadError as error:
                snapshot['errors'].append({'book_id':book_id,'scope':'progress','message':'当前进度暂未取得'})
                if error.terminal or stopped.is_set():raise
        snapshot['discovery_requests']=used
    atomic_json(cache/'annual-snapshot.json',snapshot)
    return snapshot


def deliver(snapshot, materials, covers, output, previous=None, state_path=None, allow_draft=False, distillations=None):
    from report_reader import validated_distillations
    packages = validated_distillations(distillations)
    data=annual_data(snapshot)
    data['distillations']=packages
    if previous and previous.get('year')==data['year']:
        existing={b['book_id']:b for b in previous.get('books',[])}
        for book in data['books']:
            old=existing.get(book['book_id'],{})
            for kind in ('highlights','thoughts'):
                if isinstance(old.get(kind),list):book[kind]=old[kind]
    merge_materials(data,materials)
    errors=[{'book_id':row['book_id'],'scope':e['scope'],'message':'材料暂未取得'}
            for row in materials.get('books',[]) for e in row.get('errors',[])]
    errors.extend(snapshot.get('errors',[]))
    checked=all(b.get('note_coverage',{}).get('highlights') in ('complete','unsupported') and
                b.get('note_coverage',{}).get('thoughts') in ('complete','unsupported') for b in data['books'])
    complete=data['coverage']['complete'] and checked and not errors and all(covers.get(b['book_id']) for b in data['books'])
    data['collection_status']={'complete':complete,'errors':errors,
            'message':'' if complete else '部分书目或材料尚未完整同步；刷新失败时保留上次内容。现有内容可浏览和导出，也可以重新同步缺失部分。'}
    if not complete:data['verification_status']='partial_verified'
    output=Path(output)
    result=build_html(data,output,covers,allow_draft=allow_draft)
    complete=complete and not result['missing_covers']
    if state_path:
        saved=json.loads(json.dumps(data))
        for book in saved['books']:book.pop('cover',None)
        state_path=Path(state_path);state_path.parent.mkdir(parents=True,exist_ok=True)
        atomic_json(state_path,saved)
    return {**result,'status':'complete' if complete else 'partial',
            'errors':len(errors),'message':data['collection_status']['message']}


def main():
    parser=argparse.ArgumentParser(description='接入有效微信读书Key后，自动交付单文件HTML阅读年鉴')
    parser.add_argument('--year',type=int,default=datetime.now(TZ).year)
    parser.add_argument('--distillation',type=Path,action='append',default=[],help='已完成 distillation.json，可重复提供多本')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--cache',type=Path,help='私人材料目录；默认按年份和日期缓存')
    parser.add_argument('--annual-snapshot',type=Path,help='复用已核验年度快照')
    parser.add_argument('--materials',type=Path,help='复用已有完整逐书材料，须同时提供封面映射')
    parser.add_argument('--covers',type=Path)
    parser.add_argument('--allow-draft',action='store_true',help='可选：缺封面时另存内部草稿；默认正常交付书名占位年鉴')
    parser.add_argument('--allow-large-yearbook',action='store_true',help='用户已同意逐书采集超过100本时使用')
    parser.add_argument('--refresh',choices=('reuse','missing','all'),default='reuse',help='复用缓存、重试缺失或刷新全部材料')
    parser.add_argument('--discovery-budget',type=int,default=100,help='未扩批确认时允许的新候选请求数量')
    args=parser.parse_args()
    from report_reader import load_distillations
    try:
        packages=load_distillations(args.distillation)
    except (ValueError,OSError) as error:
        print(json.dumps({'status':'blocked','message':str(error)},ensure_ascii=False));return 2
    if not 1900<=args.year<=2200:parser.error('年份须在1900—2200之间')
    if args.year>datetime.now(TZ).year:parser.error('不能采集未来年份')
    if args.discovery_budget<1:parser.error('候选请求预算须大于0')
    key=os.environ.get('WEREAD_API_KEY','').strip()
    cache=cache_directory(args.cache or Path('private/html-materials'),key,args.year)
    if (not args.annual_snapshot or not args.materials) and not key:
        print(json.dumps({'status':'missing_credentials','message':'尚未接入有效微信读书接口，请配置WEREAD_API_KEY。不会用示例数据替代你的记录。'},ensure_ascii=False));return 2
    try:
        from skill_release import check_resources,check_dependencies
        check_resources()
        check_dependencies()
        if args.refresh != 'all':
            reuse_previous_materials(cache)
        snapshot=json.loads(args.annual_snapshot.read_text('utf-8-sig')) if args.annual_snapshot else collect_snapshot(args.year,key,cache,refresh=args.refresh=='all',allow_large=args.allow_large_yearbook,request_budget=args.discovery_budget)
        if snapshot.get('year')!=args.year:raise ValueError('年度快照年份不一致')
        if args.materials:
            if not args.covers:raise ValueError('复用材料时需要封面映射')
            materials=json.loads(args.materials.read_text('utf-8-sig'))
            covers={k:str(args.covers.parent/v) for k,v in json.loads(args.covers.read_text('utf-8-sig')).items()}
        else:
            data=annual_data(snapshot)
            if len(data['books'])>100 and not args.allow_large_yearbook:
                print(json.dumps({'status':'needs_scope_confirmation','books':len(data['books']),
                    'message':'年度汇总已取得，逐书材料超过100本；先说明请求量和范围，用户确认后再扩批。'},ensure_ascii=False));return 3
            collect(data,snapshot,cache,key,refresh=args.refresh=='all')
            materials=json.loads((cache/'materials.json').read_text('utf-8'))
            covers=json.loads((cache/'covers.json').read_text('utf-8'))
        state_path=None if args.materials else cache.parent/'latest-reading-data.json'
        previous=json.loads(state_path.read_text('utf-8')) if state_path and state_path.exists() else None
        result=deliver(snapshot,materials,covers,args.output,previous,state_path,allow_draft=args.allow_draft,distillations=packages)
        print(json.dumps(result,ensure_ascii=False));return 0 if result['status']=='complete' else 2 if result['status']=='blocked' else 3
    except ScopeRequired as error:
        result=deliver(error.snapshot,{'year':args.year,'books':[]},{},args.output,distillations=packages)
        print(json.dumps({**result,'status':'needs_scope_confirmation','candidates':error.candidates,
            'message':'年度汇总已交付；候选扩查将超过本轮预算，请确认后使用--allow-large-yearbook继续。缺失封面暂用书名占位。'},ensure_ascii=False));return 3
    except (WeReadError,ValueError,OSError) as error:
        # Raw response text and credentials are never printed in delivery status.
        reason='接口、材料或资源校验失败，已保留上一版文件。请核对授权、年份与资源路径。'
        if isinstance(error,WeReadError):
            if error.kind=='auth' or any(code in str(error) for code in ('HTTP 401','HTTP 403')):reason='微信读书授权无效或已过期，请更新接口授权后再同步；已保留上一版文件。'
            elif error.kind=='upgrade' or any(code in str(error) for code in ('HTTP 499','升级')):reason='微信读书接口要求更新Skill版本，更新后再同步；已保留上一版文件。'
        elif isinstance(error,ValueError):reason=str(error)
        print(json.dumps({'status':'blocked','message':reason,'error_type':type(error).__name__},ensure_ascii=False));return 2


if __name__=='__main__':
    raise SystemExit(main())
