"""Build a private, offline reading yearbook. No network or credentials required."""
from __future__ import annotations

import argparse
import base64
import html
import json
import math
import re
import io
from datetime import datetime, timezone, timedelta
from pathlib import Path
from html_contract import category_name, reading_status, safe_link, atomic_text
from embed_fonts import font_css  # Also registers the optional local dependency directory.
from report_reader import validated_distillations, load_distillations, reader_section

ROOT = Path(__file__).resolve().parents[1]
TZ = timezone(timedelta(hours=8))


def number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) and value >= 0 else None
    except (ValueError, TypeError):
        return None


def date_value(value):
    if not value:
        return None
    try:
        if isinstance(value, (int, float)) or str(value).isdigit():
            stamp = float(value)
            return datetime.fromtimestamp(stamp / 1000 if stamp > 10**10 else stamp, TZ).strftime('%Y-%m-%d')
        match = re.match(r'^\d{4}-\d{2}-\d{2}(?:$|[ T])', str(value))
        if match:
            return datetime.strptime(str(value)[:10], '%Y-%m-%d').strftime('%Y-%m-%d')
    except (ValueError, OverflowError, OSError):
        pass
    return None


def features_data(raw,year,as_of):
    if not isinstance(raw,dict):return {}
    daily={}
    for stamp,seconds in (raw.get('daily') if isinstance(raw.get('daily'),dict) else {}).items():
        when=date_value(stamp);value=number(seconds)
        if when and int(when[:4])==year and value is not None and (not as_of or when<=as_of):daily[when]=value
    hourly=raw.get('hourly')
    categories=[]
    for row in raw.get('category_time') or []:
        if not isinstance(row,dict):continue
        seconds=number(row.get('seconds'));count=number(row.get('books'))
        if (seconds is not None and seconds>0) or (count is not None and count>0):categories.append({'name':str(row.get('name') or '未分类'),'seconds':seconds,'books':count})
    compare=raw.get('comparison')
    return {'daily':daily,'hourly':[number(n) for n in hourly] if isinstance(hourly,list) and len(hourly)==24 else [],
        'category_time':categories,'read_seconds':number(raw.get('read_seconds')),'listen_seconds':number(raw.get('listen_seconds')),
        'day_average':number(raw.get('day_average')),'comparison':compare if isinstance(compare,(int,float)) and not isinstance(compare,bool) and math.isfinite(compare) else None}


def notes(rows, year):
    if not isinstance(rows, list):
        raise ValueError('书籍划线／想法须为列表')
    result, seen = [], set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = str(row.get('text') or '').strip()
        when = date_value(row.get('created_at'))
        if not text or (year is not None and when and int(when[:4]) != year):
            continue
        source_id = str(row.get('source_id') or '')
        identity = source_id or (text, when)
        if identity in seen:
            continue
        seen.add(identity)
        result.append({'text': text, 'created_at': when, 'source_id': source_id,
                       'chapter': str(row.get('chapter_uid') or row.get('chapter') or ''), 'chapter_title': str(row.get('chapter_title') or ''),
                       'quote': str(row.get('quote') or ''), 'range':str(row.get('range') or '')})
    return result


def adapt_data(raw, year=None):
    if not isinstance(raw, dict):
        raise ValueError('年鉴数据须为对象')
    for key in ('period','coverage','sources'):
        if key in raw and not isinstance(raw[key],dict):raise ValueError(key+'须为对象')
    normalized = raw.get('schema_version') in ('reading-html/1.1','reading-html/1.2')
    if str(raw.get('schema_version','')).startswith('reading-html/') and not normalized:
        raise ValueError('不支持的HTML数据版本')
    if normalized:
        raw = json.loads(json.dumps(raw, ensure_ascii=False))
        summary = raw.get('summary')
        if not isinstance(summary, dict):
            raise ValueError('summary须为对象')
        raw['summary'] = {**summary, **{dest:summary.get(src) for src,dest in
            [('read','book_count'),('finished','finished_count'),('notes','note_count'),
             ('seconds','total_read_seconds'),('monthly','monthly_read_seconds')]}}
    year = int(year or raw.get('year') or raw.get('period', {}).get('year') or datetime.now(TZ).year)
    if not 1900 <= year <= 2200:
        raise ValueError('年份须在1900—2200之间')
    share = 'sources' in raw and 'annual_summary' in raw
    sources = raw.get('sources', {}) if share else {}
    summary = raw.get('annual_summary' if share else 'summary', {})
    rows = raw.get('books', [])
    if not isinstance(rows, list) or not isinstance(summary, dict):
        raise ValueError('books须为列表，summary须为对象')
    if 'shelf' in raw and 'stats' in raw:
        from yearbook_core import normalize_yearbook
        data=adapt_data(normalize_yearbook(raw, year), year)
        if 'distillations' in raw:
            data['distillations'] = validated_distillations(raw['distillations'], raw.get('source_mode'))
        merge_annual(data,{'year':year,'as_of':raw.get('as_of'),'shelf':raw['shelf'],'annual':raw['stats']})
        if not any(row.get('stat')=='读过' for row in raw['stats'].get('readStat',[])):
            data['summary']['read']=None;data['coverage']['annual_books']=None;data['coverage']['complete']=False
        return data
    books, seen = [], set()
    for index,row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if 'note_coverage' in row and not isinstance(row['note_coverage'],dict):
            raise ValueError(f'books[{index}].note_coverage须为对象')
        book_id = str(row.get('book_id') or '').strip()
        if not book_id or book_id in seen:
            continue
        seen.add(book_id)
        if share:
            highlights, thoughts = [], []
            for key, value in sources.items():
                if not key.startswith(book_id + '/') or key.endswith('/date') or not isinstance(value, dict):
                    continue
                dest = highlights if '/highlight/' in key else thoughts if '/thought/' in key else None
                if dest is not None:
                    dest.append({'text': value.get('text'), 'source_id': value.get('source_id', key),
                                 'created_at': value.get('created_at'), 'quote': value.get('abstract', '')})
        else:
            highlights, thoughts = row.get('highlights', []), row.get('thoughts', [])
        progress = number(row.get('progress'))
        if progress is not None and progress > 100:
            progress = None
        category = category_name(row.get('source_category') if normalized and 'source_category' in row else row.get('category'))
        primary_category = re.split(r'[-/]', category)[0].strip() if category else '未分类'
        books.append({'book_id': book_id, 'title': str(row.get('title') or '未命名书籍'),
                      'author': str(row.get('author') or '作者未记录'),
                      'category': primary_category or '未分类', 'source_category': category or '', 'category_basis': str(row.get('category_basis') or '来源分类'),
                      'progress': progress, 'status': reading_status(progress,row.get('is_started')),
                      'is_started': row.get('is_started') if isinstance(row.get('is_started'),bool) else None,
                      'kind': 'audio' if row.get('kind') == 'audio' else 'book', 'secret':row.get('secret') in (True,1),
                      'translator':str(row.get('translator') or ''), 'publisher':str(row.get('publisher') or ''), 'isbn':str(row.get('isbn') or ''),
                      'deep_link':safe_link(row.get('deep_link') or row.get('deepLink')), 'cover_url':str(row.get('cover_url') or ''),
                      'reading_seconds': number(row.get('annual_reading_seconds', row.get('reading_seconds'))),
                      'highlights': notes(highlights, None if normalized and row.get('note_coverage',{}).get('scope')=='all_time' else year),
                      'thoughts': notes(thoughts, None if normalized and row.get('note_coverage',{}).get('scope')=='all_time' else year),
                      'finish_date': date_value(row.get('finish_date') or row.get('finish_time')), 'start_date': date_value(row.get('start_date') or row.get('start_time')),
                      'intro': str(row.get('intro') or sources.get(book_id + '/intro', {}).get('text') or ''),
                      'cover': '', 'selected': row.get('selected', True) is True})
        if normalized:
            if isinstance(row.get('note_coverage'),dict):
                books[-1]['note_coverage'] = {k:row['note_coverage'].get(k) for k in ('scope','highlights','thoughts','collected_on')}
            if row.get('status') in ('finished','reading','unknown','unstarted'):
                books[-1]['status'] = row['status']
    def stat(key, fallback):
        return number(sources.get(key, {}).get('value')) if key in sources else number(fallback)
    total = stat('annual/read', summary.get('book_count'))
    as_of = date_value(raw.get('period', {}).get('as_of') or raw.get('as_of'))
    monthly = summary.get('monthly_read_seconds')
    if monthly is None:
        monthly = [None] * 12
    if not isinstance(monthly, list):
        raise ValueError('monthly_read_seconds须为列表，缺失月份用null')
    observed = summary.get('monthly_observed')
    values = []
    for i in range(12):
        value = number(monthly[i]) if i < len(monthly) else None
        if isinstance(observed, list) and (i >= len(observed) or observed[i] is not True):
            value = None
        if as_of and year == int(as_of[:4]) and i + 1 > int(as_of[5:7]):
            value = None
        values.append(value)
    # Do not present the partly collected current month as a complete month.
    complete_months = int(as_of[5:7]) - 1 if as_of and int(as_of[:4]) == year else 12
    data = {'schema_version': 'reading-html/1.2', 'year': year, 'as_of': as_of,
            'source_mode': str(raw.get('source_mode', 'unknown')),
            'verification_status': str(raw.get('coverage', {}).get('verification_status') or raw.get('verification_status') or 'unverified'),
            'coverage': {'loaded_books': len(books), 'annual_books': total,
                         'complete': total is not None and len(books) == total},
            'summary': {'read': total,
                        'finished': stat('annual/finished', summary.get('finished_count')),
                        'read_days': number(summary.get('read_days')),
                        'notes': stat('annual/notes', summary.get('note_count')),
                        'seconds': number(summary.get('total_read_seconds')),
                        'monthly': values, 'complete_months': complete_months}, 'books': books}
    if normalized:
        for key in ('collection_status','material_coverage'):
            if isinstance(raw.get(key),dict):
                data[key] = raw[key]
        coverage=raw.get('coverage',{})
        data['coverage']['complete'] = data['coverage']['complete'] and coverage.get('complete') is True
        data['coverage']['reason'] = str(coverage.get('reason') or '')
        data['features']=features_data(raw.get('features'),year,as_of)
    if 'distillations' in raw:
        data['distillations'] = validated_distillations(raw['distillations'], data['source_mode'])
    return data


def merge_annual(data, snapshot):
    """Merge positively identified year activity, never the entire shelf."""
    annual = snapshot.get('annual') or {}
    if not isinstance(annual,dict) or not isinstance(snapshot.get('shelf',{}),dict):
        raise ValueError('年度或书架快照须为对象')
    for field in ('readStat','readLongest','preferCategory'):
        if field in annual and (not isinstance(annual[field],list) or not all(isinstance(row,dict) for row in annual[field])):
            raise ValueError('年度字段'+field+'须为对象列表')
    for index,row in enumerate(annual.get('readLongest',[])):
        for field in ('book','albumInfo'):
            if row.get(field) is not None and not isinstance(row[field],dict):raise ValueError(f'annual.readLongest[{index}].{field}须为对象')
    for field in ('readTimes','dailyReadTimes'):
        if field in annual and not isinstance(annual[field],dict):raise ValueError('年度字段'+field+'须为对象')
    years = {int(date[:4]) for key in (annual.get('readTimes') or {})
             if (date := date_value(key))}
    declared_year = snapshot.get('year')
    if declared_year is not None:
        years.add(int(declared_year))
    if years != {data['year']}:
        raise ValueError('年度快照缺少可核验年份，或与年鉴年份不一致')
    # Official annual totals and current per-book progress are separate scopes.
    # Prefer an actual annual response to stale hand-entered share facts.
    for row in annual.get('readStat', []):
        key = {'读过': 'read', '读完': 'finished', '笔记': 'notes'}.get(row.get('stat'))
        count = re.fullmatch(r'\s*(\d+)\s*(?:本|条)?\s*', str(row.get('counts','')))
        if key and count:
            data['summary'][key] = int(count[1])
    for field, key in [('readDays', 'read_days'), ('totalReadTime', 'seconds')]:
        if number(annual.get(field)) is not None:
            data['summary'][key] = number(annual[field])
    if date_value(snapshot.get('as_of')):
        data['as_of'] = date_value(snapshot['as_of'])
        data['summary']['complete_months'] = int(data['as_of'][5:7])-1 if int(data['as_of'][:4]) == data['year'] else 12
    if annual.get('readTimes'):
        monthly = [None]*12
        for timestamp, seconds in annual['readTimes'].items():
            date = date_value(timestamp)
            if date and int(date[:4]) == data['year']:
                month = int(date[5:7])-1
                if not data['as_of'] or int(data['as_of'][:4]) != data['year'] or month < int(data['as_of'][5:7]):
                    monthly[month] = number(seconds)
        data['summary']['monthly'] = monthly
    shelf = {str(b.get('bookId')): b for b in snapshot.get('shelf', {}).get('books', [])}
    existing = {b['book_id']: b for b in data['books']}
    ranked = {str((x.get('book') or {}).get('bookId')): x for x in annual.get('readLongest', []) if number(x.get('readTime')) and (x.get('book') or {}).get('bookId')}
    candidates = {key: {**shelf.get(key, {}), **item['book']} for key, item in ranked.items()}
    status = {}
    for item in snapshot.get('non_ranked_progress', []):
        key = str(item.get('book_id') or '')
        status[key] = item
        date = date_value(item.get('last_read'))
        finished = date_value(item.get('finished_on'))
        if (item.get('is_started') and date and int(date[:4]) == data['year']) or (finished and int(finished[:4])==data['year']) or item.get('year_note_evidence'):
            candidates.setdefault(key, {**shelf.get(key, {}), 'title': item.get('title')})
    for key, row in candidates.items():
        b = existing.get(key)
        if not b:
            b = adapt_data({'year': data['year'], 'books': [{'book_id': key, 'title': row.get('title'), 'author': row.get('author')}], 'summary': {}})['books'][0]
            b['selected'] = False
            existing[key] = b
        category = row.get('category')
        if isinstance(category, str) and category:
            b['source_category'] = category
            b['category'] = re.split(r'[-/]', category)[0].strip() or '未分类'
        elif isinstance(category, dict):
            b['category'] = str(category.get('title') or category.get('categoryTitle') or '未分类')
        info = status.get(key, {})
        b['secret'] = row.get('secret') in (True,1)
        b['is_started'] = info.get('is_started') if isinstance(info.get('is_started'),bool) else None
        progress = number(info.get('progress'))
        if progress is not None and progress <= 100:
            b['progress'] = progress
            b['status'] = reading_status(progress,b['is_started'])
        if key in ranked:
            b['reading_seconds'] = number(ranked[key]['readTime'])
        if info.get('finished_on'):
            b['finish_date'] = date_value(info['finished_on'])
    data['books'] = list(existing.values())
    albums={str((x.get('albumInfo') or {}).get('albumId')):x for x in (snapshot.get('shelf',{}).get('albums') or []) if isinstance(x,dict) and isinstance(x.get('albumInfo') or {},dict)}
    for item in annual.get('readLongest',[]):
        album=item.get('albumInfo') or {}
        if not album.get('albumId') or not number(item.get('readTime')):
            continue
        key='audio-'+str(album['albumId'])
        if key in existing:
            continue
        source=albums.get(str(album['albumId']),{})
        book=adapt_data({'year':data['year'],'books':[{'book_id':key,'title':album.get('name') or album.get('title'),
            'author':album.get('authorName'),'intro':album.get('intro'),'kind':'audio','cover_url':album.get('cover'),
            'secret':source.get('albumInfoExtra',{}).get('secret'), 'annual_reading_seconds':item['readTime']}], 'summary':{}})['books'][0]
        existing[key]=book
    data['books']=list(existing.values())
    data['coverage']['annual_books'] = data['summary']['read']
    data['coverage']['loaded_books'] = len(existing)
    data['coverage']['complete'] = len(existing) == data['coverage']['annual_books']
    if snapshot.get('discovery_incomplete') or snapshot.get('errors'):
        data['coverage']['complete'] = False
    data['coverage']['reason'] = '' if data['coverage']['complete'] else '接口排行与候选书目不足以确认完整年度书单'
    daily={}
    for stamp,seconds in (annual.get('dailyReadTimes') or {}).items():
        when=date_value(stamp);value=number(seconds)
        if when and int(when[:4])==data['year'] and value is not None and (not data['as_of'] or when<=data['as_of']):
            daily[when]=value
    times=annual.get('preferTime')
    categories=[]
    for row in annual.get('preferCategory',[]):
        seconds=number(row.get('readingTime'));count=number(row.get('readingCount'))
        if (seconds is not None and seconds>0) or (count is not None and count>0):
            categories.append({'name':str(row.get('parentCategoryTitle') or row.get('categoryTitle') or '未分类'),
                               'seconds':seconds,'books':count})
    data['features']=features_data({'daily':daily,'hourly':([number(times[(hour-6)%24]) for hour in range(24)] if isinstance(times,list) and len(times)==24 else []),
                      'category_time':categories,'read_seconds':number(annual.get('wrReadTime')),
                      'listen_seconds':number(annual.get('wrListenTime')),'day_average':number(annual.get('dayAverageReadTime')),
                      'comparison':annual.get('compare')},data['year'],data['as_of'])
    return data


def merge_materials(data, materials):
    """Fill known books only. Failed collection never means an empty notebook."""
    if materials.get('year') != data['year']:
        raise ValueError('书籍材料年份与年鉴不一致')
    existing = {b['book_id']: b for b in data['books']}
    for row in materials.get('books', []):
        b = existing.get(str(row.get('book_id') or ''))
        if b is None:
            continue
        coverage = row.get('collection') or {}
        for key in ('title', 'author', 'intro','translator','publisher','isbn'):
            if row.get(key):
                b[key] = str(row[key])
        if category_name(row.get('category')):
            b['source_category']=category_name(row['category'])
            b['category']=re.split(r'[-/]',b['source_category'])[0].strip() or '未分类'
        b['deep_link']=safe_link(row.get('deepLink') or row.get('deep_link') or b.get('deep_link'))
        if coverage.get('progress') in ('complete','stale'):
            progress = number(row.get('progress'))
            if progress is not None and progress <= 100:
                b['progress'] = progress
                if isinstance(row.get('is_started'),bool): b['is_started']=row['is_started']
                b['status'] = reading_status(progress,b.get('is_started'))
            finish = date_value(row.get('finish_time'))
            if finish and int(finish[:4]) == data['year']:
                b['finish_date'] = finish
        note_year = None if row.get('notes_scope') == 'all_time' else data['year']
        for key in ('highlights', 'thoughts'):
            if coverage.get(key) in ('complete','unsupported','stale'):
                b[key] = notes(row.get(key, []), note_year)
            elif coverage.get(key)=='partial':
                b[key]=notes([*row.get(key,[]),*b.get(key,[])],note_year)
        b['note_coverage'] = {'scope': 'all_time' if note_year is None else 'year',
                              'highlights': coverage.get('highlights') if coverage.get('highlights') in ('complete','unsupported','stale','partial') else 'unverified',
                              'thoughts': coverage.get('thoughts') if coverage.get('thoughts') in ('complete','unsupported','stale','partial') else 'unverified',
                              'collected_on': date_value(row.get('collected_on'))}
    data['material_coverage'] = {'books_with_checked_highlights': sum(b.get('note_coverage', {}).get('highlights') == 'complete' for b in data['books']),
                                 'books_with_checked_thoughts': sum(b.get('note_coverage', {}).get('thoughts') == 'complete' for b in data['books']),
                                 'current_finished': sum(b['status'] == 'finished' for b in data['books']),
                                 'states_collected_on': max((b.get('note_coverage', {}).get('collected_on') or '' for b in data['books']), default='')}
    return data


def embed_image(path):
    from cover_contract import image_data
    path = Path(path)
    return image_data(path.read_bytes(),path.name)


def build_html(data, output, covers=None, art_assets=None, require_all_covers=False, allow_draft=False):
    """Whitelist data at adapter boundary; no raw payload embedded."""
    validated_distillations(data.get('distillations'), data.get('source_mode'))
    from cover_contract import missing_covers, MissingCovers
    strict=require_all_covers
    invalid_files=set()
    for b in data['books']:
        for removed in ('review', 'full_text_review', 'full_text_search'):
            b.pop(removed, None)
        if (covers or {}).get(b['book_id']):
            try:
                b['cover'] = embed_image(covers[b['book_id']])
            except (ValueError,OSError):
                b['cover']=''; invalid_files.add(b['book_id'])
    missing=missing_covers(data)
    for row in missing:
        if row['book_id'] in invalid_files: row['reason']='invalid'
    if strict and missing: raise MissingCovers(missing)
    missing_ids={row['book_id'] for row in missing}
    for book in data['books']:
        if book['book_id'] in missing_ids: book['cover']=''
    if missing and 'collection_status' in data:
        data['collection_status']['complete']=False
        data['collection_status']['message']='部分封面或材料暂未取得，年度报告仍可正常浏览和导出。'
        data['verification_status']='partial_verified'
    serialized = json.dumps(data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    if re.search(r'wrk-[A-Za-z0-9_-]{8,}', serialized):
        raise ValueError('交付内容中检测到密钥格式，请移除后重试')
    template = (ROOT / 'assets' / 'reading-template.html').read_text('utf-8')
    # Art belongs to presentation, never the user's exported reading JSON.
    unknown = set(art_assets or {}) - {'hero', 'reading', 'rhythm'}
    if unknown:
        raise ValueError('未知艺术素材字段：' + ', '.join(sorted(unknown)))
    art = {name: embed_image((art_assets or {}).get(name) or ROOT / 'assets' / 'yearbook-art' / file)
           for name, file in [('hero', 'hero-book.png'), ('reading', 'reading.png'), ('rhythm', 'rhythm.png')]}
    replacements = {'__DATA__': serialized, '__STYLE__': (ROOT / 'assets' / 'reading-app.css').read_text('utf-8') + '\n' + (ROOT / 'assets' / 'reading-art.css').read_text('utf-8') + '\n' + (ROOT / 'assets' / 'ebook-app.css').read_text('utf-8'),
                    '__ART__': json.dumps(art),
                    '__APP__': (ROOT / 'assets' / 'reading-app.js').read_text('utf-8'),
                    '__SHARE_APP__': (ROOT / 'assets' / 'reading-share-art.js').read_text('utf-8'),
                    '__EBOOK_APP__': (ROOT / 'assets' / 'ebook-app.js').read_text('utf-8'),
                    '__EBOOK_SECTION__': reader_section(),
                    '__LICENSE__': html.escape((ROOT / 'assets' / 'lieflat-LICENSE.txt').read_text('utf-8')+'\n\nNoto Serif SC\n'+(ROOT/'assets/fonts/OFL-Serif.txt').read_text('utf-8')+'\n\nNoto Sans SC\n'+(ROOT/'assets/fonts/OFL-Sans.txt').read_text('utf-8'))}
    # One-pass replacement: user text may itself contain template delimiters.
    page = re.sub(r'__(?:DATA|STYLE|APP|SHARE_APP|EBOOK_APP|EBOOK_SECTION|LICENSE|ART)__', lambda m: replacements[m.group()], template)
    if missing and allow_draft:
        notice=f'<section role="status" data-reading-draft="true"><h2>内部草稿</h2><p>{len(missing)}本书暂用书名封面。</p></section>'
        page=page.replace('<main>','<main>'+notice,1)
    output = Path(output)
    if missing and allow_draft and not output.stem.endswith('-draft'):
        output=output.with_name(output.stem+'-draft'+output.suffix)
    output.parent.mkdir(parents=True, exist_ok=True)
    atomic_text(output,page)
    return {'output': str(output), 'bytes': output.stat().st_size, 'books': len(data['books']), 'coverage': data['coverage'],
            'missing_covers':len(missing),'missing_books':missing}


def main():
    parser = argparse.ArgumentParser(description='生成单文件离线阅读年鉴，保留原分享与atlas流程')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--year', type=int)
    parser.add_argument('--distillation', type=Path, action='append', default=[], help='已完成 distillation.json，可重复提供多本')
    parser.add_argument('--annual-snapshot', type=Path)
    parser.add_argument('--covers', type=Path, help='JSON：book_id到本地书封路径，路径相对该JSON')
    parser.add_argument('--art-assets', type=Path, help='JSON：hero/reading/rhythm到本地透明图片路径，可按认可方向替换')
    parser.add_argument('--book-materials', type=Path, help='补采的进度与完整笔记材料，不能用精选摘录冒充完整采集')
    parser.add_argument('--require-all-covers', action='store_true', help='正式年鉴缺任一本封面时停止，不覆盖上一版')
    parser.add_argument('--allow-draft', action='store_true', help='可选：缺封面时另存内部草稿；默认正常交付书名占位年鉴')
    args = parser.parse_args()
    try:
        raw = json.loads(args.input.read_text('utf-8-sig'))
        if not isinstance(raw, dict):
            raise ValueError('年鉴数据须为对象，请先提供已有材料并蒸馏至少一本。')
        if args.distillation:
            raw['distillations'] = load_distillations(args.distillation, raw.get('source_mode'))
        validated_distillations(raw.get('distillations'), raw.get('source_mode'))
    except (ValueError, OSError) as error:
        print(json.dumps({'status':'blocked','message':str(error)},ensure_ascii=False))
        return 2
    data = adapt_data(raw, args.year)
    if args.annual_snapshot:
        merge_annual(data, json.loads(args.annual_snapshot.read_text('utf-8-sig')))
    if args.book_materials:
        merge_materials(data, json.loads(args.book_materials.read_text('utf-8-sig')))
    covers = {}
    if args.covers:
        covers = {k: args.covers.parent / v for k, v in json.loads(args.covers.read_text('utf-8-sig')).items()}
    art_assets = {}
    if args.art_assets:
        art_assets = {k: args.art_assets.parent / v for k, v in json.loads(args.art_assets.read_text('utf-8-sig')).items()}
    print(json.dumps(build_html(data, args.output, covers, art_assets, args.require_all_covers,allow_draft=args.allow_draft), ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
