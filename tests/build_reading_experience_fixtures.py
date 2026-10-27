"""Small synthetic fixtures, never copied from personal reading records."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data, build_html, merge_materials
from test_report_reader import bundle

out=Path(sys.argv[1] if len(sys.argv)>1 else 'demo-output/reading-experience')
for kind in ['notes','none','failed','empty','long','many']:
    rows=[] if kind=='empty' else [{'book_id':str(i),'title':'书名'+str(i)+('很长的中文书名'*16 if kind=='long' and i==1 else ''),'author':'作者','category':'文学','progress':50} for i in range(73 if kind=='many' else 7)]
    if kind=='many':rows[-1]['title']='书名最后一本'
    data=adapt_data({'year':2026,'source_mode':'sample','distillations':[bundle(sample=True)],'summary':{'book_count':len(rows)},'books':rows})
    materials={'year':2026,'books':[{'book_id':b['book_id'],'notes_scope':'all_time','collection':{'highlights':'failed' if kind=='failed' else 'complete','thoughts':'failed' if kind=='failed' else 'complete'},
        'thoughts':[{'text':'只写了个人想法，不是书中引文','source_id':'note','created_at':'2026-10-01'}] if kind=='notes' else [],
        'highlights':[{'text':'这是一条用于检查控件的示例划线','source_id':'line'}] if kind=='long' else []} for b in data['books']]}
    merge_materials(data,materials)
    if kind=='failed':data['collection_status']={'complete':False,'message':'部分材料暂未取得，请让助手重新同步。','errors':[{'scope':'highlights'}]}
    build_html(data,out/f'{kind}.html')
print('Built synthetic material states and varying shelf sizes.')
