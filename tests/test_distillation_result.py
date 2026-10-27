import copy
import importlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))


def fixture(mode='upload'):
    source = {'element_id':'e1','quote':'先检查输入。','location':'第一节'}
    document = {'source_hash':'a'*64,'book':{'title':'受控短篇','author':'测试作者'},
                'elements':[dict(source, text='先检查输入。然后根据条件行动。', source_type='preview' if mode=='title' else 'text')]}
    analysis = {'schema_version':1,'book':dict(document['book']),'overview':'这篇短文介绍行动前的检查。',
                'themes':[{'title':'先检查','explanation':'先判断输入是否齐全。','sources':[source]}],
                'methods':[],'cases':[],'counterexamples':[],'glossary':[],'limitations':[],
                'source_hash':document['source_hash'],'input_mode':mode,'quality_status':'needs_review',
                'coverage':{'scope_note':'公开资料，未核验全文' if mode=='title' else '所提供正文',
                            'complete':mode=='upload', **({'full_text':False} if mode=='title' else {})},
                'reading_lenses':[{'id':'v1','kind':'values','title':'全书最在意的事','text':'行动应先检查输入。','sources':[source]}],
                'memorable_passages':[{'text':'先检查输入。','why_it_matters':'概括了检查的顺序。','sources':[source]}]}
    return analysis, document


class BundleTests(unittest.TestCase):
    def api(self):
        spec = importlib.util.find_spec('distillation_result')
        self.assertIsNotNone(spec, 'Missing reusable distillation result API')
        return importlib.import_module('distillation_result')

    def test_both_modes_roundtrip_and_sample_marker(self):
        api = self.api()
        for mode in ('title','upload'):
            analysis, document = fixture(mode)
            document['source_mode'] = 'sample'
            bundle = api.make_bundle(analysis, document, '# 受控摘要')
            self.assertEqual(bundle['source_mode'], 'sample')
            self.assertEqual(bundle['checks']['semantic_validation'], 'not_independent')
            self.assertNotIn('elements', json.dumps(bundle))
            self.assertEqual(api.validate_bundle(bundle), bundle)
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp)/'distillation.json'
                path.write_text(json.dumps(bundle), encoding='utf-8')
                self.assertEqual(api.load_bundle(path), bundle)

    def test_rejects_empty_identity_bad_source_and_hash_binding(self):
        api = self.api()
        for change in ('empty','identity','blank_content','quote','hash','book','mode'):
            analysis, document = fixture()
            if change == 'empty': analysis = {}
            if change == 'identity': analysis['themes'] = []
            if change == 'blank_content':analysis['themes'][0]['explanation']=' '
            if change == 'quote': analysis['themes'][0]['sources'][0]['quote'] = '虚构'
            if change == 'hash': analysis['source_hash'] = 'b'*64
            if change == 'book': analysis['book']['title'] = '另一本'
            if change == 'mode': analysis['input_mode'] = 'sample'
            with self.subTest(change=change), self.assertRaises(ValueError): api.make_bundle(analysis,document)

    def test_rejects_tamper_and_resealed_identity_mode_change(self):
        api = self.api()
        bundle = api.make_bundle(*fixture())
        for key in ('digest','source_hash','input_mode','checks','analysis'):
            changed = copy.deepcopy(bundle)
            changed[key] = {} if key in ('checks','analysis') else 'changed'
            with self.subTest(key=key), self.assertRaises(ValueError): api.validate_bundle(changed)
        for key in ('book','input_mode','source_hash'):
            changed=copy.deepcopy(bundle)
            changed['analysis'][key] = {'title':'另一本','author':'作者'} if key=='book' else ('title' if key=='input_mode' else 'b'*64)
            changed['bundle_hash']=api.bundle_hash(changed)
            with self.subTest(key=key), self.assertRaises(ValueError): api.validate_bundle(changed)

    def test_reading_fields_require_exact_original_passages(self):
        api = self.api()
        for change in ('lens','passage','secondary','note','kind'):
            analysis, document = fixture('title')
            if change=='lens': analysis['reading_lenses'][0]['sources']=[]
            if change=='passage': analysis['memorable_passages'][0]['text']='漂亮但不存在的句子'
            if change=='secondary': document['elements'][0]['source_type']='secondary'
            if change=='note': document['elements'][0]['source_type']='source_notes'
            if change=='kind': analysis['reading_lenses'][0]['kind']='intent'
            with self.subTest(change=change), self.assertRaises(ValueError): api.make_bundle(analysis,document)

    def test_private_fields_are_not_exported_and_resealed_empty_sources_fail(self):
        api=self.api();analysis,document=fixture()
        analysis.update(execution_identity={'session':'private'},prompt='whole private source',
                        document=document,token='private-token',audit=[document])
        analysis['themes'][0]['token']='private-token'
        bundle=api.make_bundle(analysis,document)
        serialized=json.dumps(bundle)
        for key in ('private-token','whole private source','execution_identity','"audit"','"elements"'):
            self.assertNotIn(key,serialized)
        bundle['analysis']['themes'][0]['sources']=[]
        bundle['bundle_hash']=api.bundle_hash(bundle)
        with self.assertRaises(ValueError):api.validate_bundle(bundle)

    def test_source_document_mode_cannot_be_mixed(self):
        api=self.api();analysis,document=fixture('upload')
        document['bibliography']=[{'type':'secondary'}]
        with self.assertRaises(ValueError):api.make_bundle(analysis,document)
        analysis,document=fixture('title');document['elements'][0].pop('source_type');analysis['memorable_passages']=[]
        with self.assertRaises(ValueError):api.make_bundle(analysis,document)

    def test_public_nested_objects_project_known_fields_only(self):
        api=self.api();analysis,document=fixture('title')
        source=analysis['themes'][0]['sources'][0]
        verification={'status':'needs_review','reason':'待核查','V1':True,'V2':False,'V3':False,
                      'source_sufficiency':{'reason':'原文有依据'},
                      'walkthrough':{'input':'输入','steps':['检查'],'output':'结果','completion_standard':'完成检查'},
                      'task_utility':'检查输入','semantic_evaluation':'non_isolated_current_agent','blind_baseline':False}
        analysis.update(book_context=[{'kind':'logic','title':'论证','explanation':'先检查再行动','sources':[source]}],
            methods=[{'id':'m1','title':'检查','interpretation':'检查输入','trigger':'行动前','steps':['检查'],
                      'example':'核对输入','boundaries':['缺失时停止'],'candidate_ids':['c1'],
                      'verification':verification,'sources':[source]}],
            cases=[{'title':'检查案例','explanation':'检查后行动','case_origin':'ai_exercise','sources':[source]}],
            counterexamples=[{'title':'跳过检查','explanation':'会遗漏输入','sources':[source]}],
            glossary=[{'term':'检查','definition':'核对输入','sources':[source]}],
            insights=[{'title':'检查习惯','explanation':'先检查','sources':[source]}],
            references=[{'id':'r1','title':'参考','summary':'有来源','original_candidate_ids':['c1'],
                         'verification':{'status':'reference','reason':'参考材料'},'sources':[source]}],
            review={'status':'ready','reason':'','paragraphs':[{'text':'我留意到“先检查输入。”这句话。','sources':[source],'quotes':[source]}]},
            content_map=[{'id':'t1','title':'检查','importance':'core','status':'read','gap':'','sources':[source]}],
            topic_coverage=[{'topic_id':'t1','status':'explained','item_refs':['themes:0'],'reason':'已解释'}],
            reading_status={'level':'public_reading','label':'公开资料解读','reason':'限本次资料'},
            structure_index=[{'title':'第一节','element_ids':['e1']}],
            decision_rules=[{'method_id':'m1','title':'检查','trigger':'行动前','steps':['检查'],
                             'interpretation':'检查输入','boundaries':['缺失时停止'],'sources':[source],'verification':verification}],
            bibliography=[{'id':'s1','url':'https://example.org/book','title':'试读','type':'preview',
                           'accessed_at':'2026-10-01','content_hash':'b'*64,'content_kind':'excerpt'}])
        analysis['book'].update(id='b1',edition='第一版',identity_url='https://example.org/book')
        document['book']=copy.deepcopy(analysis['book'])
        analysis['coverage'].update(key_tasks=[{'id':'t1','title':'检查','sources':[source]}],
            task_audit=[{'task_id':'t1','status':'needs_review','candidate_ids':['c1'],'reason':'待核查'}],
            candidate_dispositions=[{'id':'c1','status':'needs_review','reason':'待核查','task_ids':['t1'],
                'sources':[source],'verification':verification,'delivered_methods':['m1'],
                'delivered_reference':None,'final_status':'needs_review'}],
            excluded_boilerplate=[{'kind':'epub-navigation','wrapper_id':'nav'}])
        expected=api.make_bundle(analysis,document)
        seen=set()
        def inject(value):
            if id(value) in seen:return
            seen.add(id(value))
            if isinstance(value,dict):
                for item in list(value.values()):inject(item)
                value.update({key:{'secret':'NEVER-PUBLIC'} for key in
                    ('source_text','agent_token','document','prompt','private_audit','unknown_object')})
            elif isinstance(value,list):
                for item in value:inject(item)
        inject(analysis)
        document['book']=copy.deepcopy(analysis['book'])
        bundle=api.make_bundle(analysis,document)
        self.assertFalse('NEVER-PUBLIC' in json.dumps(bundle),'Unknown nested keys leaked into the public bundle')
        self.assertEqual(bundle,expected,'Projection must retain all supported public fields and source boundaries')
        self.assertIn('NEVER-PUBLIC',json.dumps(analysis),'Caller input remains private and unmodified')
        for target in (bundle['analysis']['themes'][0],bundle['analysis']['methods'][0]['verification']['walkthrough'],
                       bundle['checks'],bundle['checks']['evidence'][0]):
            with self.subTest(target=list(target)):
                changed=copy.deepcopy(bundle)
                # Locate the matching object in the copy without changing valid evidence.
                def taint(value):
                    if isinstance(value,dict):
                        if value==target:value['unknown_object']={'secret':'NEVER-PUBLIC'};return True
                        return any(taint(item) for item in value.values())
                    if isinstance(value,list):return any(taint(item) for item in value)
                    return False
                self.assertTrue(taint(changed))
                changed['bundle_hash']=api.bundle_hash(changed)
                with self.assertRaises(ValueError):api.validate_bundle(changed)

    def test_resealed_unknown_public_objects_are_rejected(self):
        api=self.api();bundle=api.make_bundle(*fixture())
        for section in ('theme','source','book','coverage','checks','evidence'):
            changed=copy.deepcopy(bundle)
            targets={'theme':changed['analysis']['themes'][0],
                     'source':changed['analysis']['themes'][0]['sources'][0],
                     'book':changed['analysis']['book'],'coverage':changed['analysis']['coverage'],
                     'checks':changed['checks'],'evidence':changed['checks']['evidence'][0]}
            targets[section]['unknown_object']={'source_text':'NEVER-PUBLIC'}
            if section=='book':changed['checks']['book']=copy.deepcopy(changed['analysis']['book'])
            changed['bundle_hash']=api.bundle_hash(changed)
            with self.subTest(section=section),self.assertRaises(ValueError):api.validate_bundle(changed)

    def test_merged_candidate_lineage_survives_public_projection(self):
        api=self.api()
        for mode in ('upload','title'):
            analysis,document=fixture(mode)
            method={'id':'m1','title':'检查','interpretation':'检查输入','trigger':'行动前',
                    'steps':['检查'],'example':'核对输入','boundaries':['缺失时停止'],
                    'candidate_ids':['c1'],'original_candidate_ids':['c1','c2'],
                    'sources':copy.deepcopy(analysis['themes'][0]['sources']),
                    'verification':{'status':'needs_review','reason':'合并候选后待核查'},
                    'unknown_object':{'source_text':'NEVER-PUBLIC'},'agent_token':'NEVER-PUBLIC'}
            analysis['methods']=[method]
            analysis['decision_rules']=[dict(copy.deepcopy(method),method_id='m1')]
            bundle=api.make_bundle(analysis,document)
            self.assertFalse('NEVER-PUBLIC' in json.dumps(bundle),'Unknown fields must still be removed')
            for section in ('methods','decision_rules'):
                with self.subTest(mode=mode,section=section):
                    self.assertEqual(bundle['analysis'][section][0].get('original_candidate_ids'),['c1','c2'])
                    self.assertEqual(bundle['analysis'][section][0]['candidate_ids'],['c1'])
            self.assertEqual(api.validate_bundle(bundle),bundle)

    def test_public_scalar_fields_cannot_smuggle_nested_objects(self):
        api=self.api();analysis,document=fixture()
        analysis['coverage']['scope_note']={'source_text':'private'}
        with self.assertRaises(ValueError):api.make_bundle(analysis,document)
        analysis,document=fixture()
        analysis['themes'][0]['sources'][0]['url']={'source_text':'private'}
        with self.assertRaises(ValueError):api.make_bundle(analysis,document)

    def test_resealed_ready_review_reapplies_paragraph_and_quote_contract(self):
        api=self.api();analysis,document=fixture()
        source=analysis['themes'][0]['sources'][0]
        analysis['review']={'status':'ready','reason':'','paragraphs':[
            {'text':'我留意到“先检查输入。”这句话。','sources':[source],'quotes':[source]}]}
        bundle=api.make_bundle(analysis,document)
        for change in ('unbound','unrecorded_quote','wrong_punctuation','absent_quote','missing_quotes','empty_ready'):
            changed=copy.deepcopy(bundle);review=changed['analysis']['review'];paragraph=review['paragraphs'][0]
            if change=='unbound':paragraph.update(text='没有依据的书评',sources=[],quotes=[])
            if change=='unrecorded_quote':paragraph['quotes']=[]
            if change=='wrong_punctuation':paragraph['text']='我留意到“先检查输入！”这句话。'
            if change=='absent_quote':paragraph['text']='我留意到检查顺序。'
            if change=='missing_quotes':paragraph.pop('quotes')
            if change=='empty_ready':review['paragraphs']=[]
            changed['bundle_hash']=api.bundle_hash(changed)
            with self.subTest(change=change),self.assertRaises(ValueError):api.validate_bundle(changed)

    def test_review_remains_optional_or_explicitly_unavailable(self):
        api=self.api()
        for mode in ('upload','title'):
            for unavailable in (False,True):
                analysis,document=fixture(mode)
                if unavailable:analysis['review']={'status':'unavailable','reason':'材料不足，暂未生成书评','paragraphs':[]}
                with self.subTest(mode=mode,unavailable=unavailable):
                    bundle=api.make_bundle(analysis,document)
                    self.assertEqual(api.validate_bundle(bundle),bundle)
if __name__ == '__main__': unittest.main()
