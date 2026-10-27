"""Small self-contained reader fixture; no model, network or private records."""
import argparse
import hashlib
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data,build_html
from distillation_result import make_bundle


def sample_bundle(index,mode):
    text=('先核实日期。资料不全时，先找负责人问清楚，再决定下一步。' if index==1 else
          '给未知留一行。把未核实的条件写下来，指定负责核实的人，再约定回来的时间。')
    quote=text.split('。')[0]+'。'
    book={'title':f'受控短篇{index}','author':'测试作者'}
    source={'element_id':f'fixture-{index}','quote':quote,'location':'受控短篇第一段'}
    source_hash=hashlib.sha256(text.encode('utf-8')).hexdigest()
    document={'book':book,'source_hash':source_hash,'source_mode':'sample','input_mode':mode,
              'elements':[{'element_id':source['element_id'],'text':text,'location':source['location'],
                           'source_type':'preview' if mode=='title' else 'text'}]}
    analysis={'schema_version':1,'book':book,'source_hash':source_hash,'input_mode':mode,
              'overview':('先核实日期，资料不足时询问负责人。' if index==1 else '给未知条件分配核实责任与返回时间。'),
              'themes':[{'title':'先核实再行动' if index==1 else '为未知安排下一步',
                         'explanation':'先核对缺少的日期。' if index==1 else '为未核实的条件安排负责人和时间。',
                         'sources':[source]}],
              'methods':[],'cases':[],'counterexamples':[],'glossary':[],
              'quality_status':'needs_review','limitations':['受控功能测试；非真实出版物或个人阅读记录，未调用模型。'],
              'coverage':{'complete':mode=='upload','scope_note':'仅覆盖自写的受控功能测试材料。',
                          **({'full_text':False,'sources_read':1} if mode=='title' else {})},
              'reading_lenses':[{'id':f'lens-{index}','kind':'values' if index==1 else 'connections',
                    'title':'检查的顺序' if index==1 else '读完想试的一件事',
                    'text':'先问清楚缺少什么日期。' if index==1 else '给未知留一行，写清谁去核实、什么时候回来。',
                    'sources':[source]}],
              'memorable_passages':[{'text':quote,'why_it_matters':'这句话指出了行动前要补齐的条件。','sources':[source]}]}
    return make_bundle(analysis,document)


def build_fixture(output):
    data=adapt_data({'year':2026,'source_mode':'sample','summary':{'book_count':0},'books':[],
                     'distillations':[sample_bundle(1,'upload'),sample_bundle(2,'title')]})
    return build_html(data,output)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    build_fixture(args.output)
