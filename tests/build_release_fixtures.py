"""Synthetic documents only; no credentials or private reading records."""
import json
import sys
from datetime import datetime
from pathlib import Path
from PIL import Image,ImageDraw

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data,build_html,merge_annual,merge_materials,TZ
from test_report_reader import bundle


def main():
    out=ROOT/'demo-output/release-validation';out.mkdir(parents=True,exist_ok=True)
    for name,count in [('empty',0),('mixed',12),('long',4),('large',100),('january',1)]:
        books=[];covers={}
        for i in range(count):
            book_id=str(i)
            cover=out/f'cover-{i}.png'
            if not cover.exists():
                image=Image.new('RGB',(180,270),['#cfb787','#527087','#83907c'][i%3]);draw=ImageDraw.Draw(image);draw.rectangle((14,14,166,256),outline='#f5eedc',width=2);draw.text((25,100),f'BOOK {i+1}',fill='#f5eedc');image.save(cover)
            title='示例阅读书'+str(i+1)
            if name=='long':title=('繁体與简体：'+('长标题与👩‍💻组合字形及无空格EnglishTitle'*8)) if i==0 else '长标题阅读测试'*18
            books.append({'book_id':book_id,'title':title,'author':('长作者姓名与共同创作'*10) if name=='long' else '示例作者'+str(i),
                'category':['文学-小说','经济-商业','未分类'][i%3],'progress':[0,1,100,None][i%4],'is_started':[True,True,True,None][i%4],
                'annual_reading_seconds':None if i%4==3 else 1200*(i+1),'secret':i==1,'finish_time':'2026-06-01' if i%4==2 else None,
                'intro':'测试用内容简介。'*40 if i%3==0 else '',
                'highlights':[{'text':('这是用于验证排版的示例原文，保留文字与材料类型。'*24 if name=='long' else '这是一条示例划线。'),'source_id':f'h{i}','created_at':'2026-06-01'}] if i%3!=1 else [],
                'thoughts':[{'text':'这是个人想法，与原文分开。','quote':'对应的示例原文。','source_id':f'n{i}','created_at':'2025-06-01'}] if i%3!=2 else []})
            covers[book_id]=cover
        raw={'year':2026,'as_of':'2026-01-20' if name=='january' else '2026-10-06','source_mode':'sample','verification_status':'sample_verified',
            'summary':{'book_count':count,'finished_count':count//3,'note_count':count*2,'read_days':174,'total_read_seconds':3600*45+21*60,'monthly_read_seconds':[3600,None,0,7200,1800,1200,4400,6600,3300,120]},'books':books}
        raw['distillations']=[bundle(sample=True)]
        data=adapt_data(raw)
        merge_materials(data,{'year':2026,'books':[{**b,'notes_scope':'all_time','collection':{'highlights':'complete','thoughts':'complete'}} for b in books]})
        if name=='mixed':
            data['features']={'daily':{'2026-01-01':120,'2026-01-02':300,'2026-06-01':0},'hourly':[3600 if i==6 else 0 for i in range(24)],
                'category_time':[{'name':'文学','seconds':3000,'books':4}], 'read_seconds':3600,'listen_seconds':1800,'day_average':180,'comparison':-.2}
            data['books'][1]['thoughts']=[{'text':f'第{i}条示例笔记','created_at':'2026-06-01','source_id':f'n-{i}','quote':'原文','chapter':'1','chapter_title':'第一章','range':'1-2'} for i in range(1000)]
        build_html(data,out/(name+'.html'),covers,require_all_covers=True)
    print(json.dumps({'output':str(out),'fixtures':5},ensure_ascii=False))


if __name__=='__main__':main()
