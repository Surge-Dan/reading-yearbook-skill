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


if __name__ == '__main__': unittest.main()
