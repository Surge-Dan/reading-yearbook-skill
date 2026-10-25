import importlib
import importlib.util
import inspect
import json
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))
from serve_ebook import JobStore, valid_saved_job, workbench_page
from ebook_agent_bridge import AgentRunner


def library(test):
    test.assertIsNotNone(importlib.util.find_spec('ebook_title'), '独立书名资料管线尚未实现')
    return importlib.import_module('ebook_title')


def evidence():
    return {'book_key': 'b1', 'searches_used': 1, 'gaps': ['未获得整书'],
        'content_map':[{'id':'t1','title':'记录与比较','importance':'core','status':'read','gap':'',
                        'sources':[{'element_id':'s1-1','quote':'先记录问题，再比较两个方案。','location':'作者资料'}]}], 'sources': [
        {'id': 's1', 'book_key': 'b1', 'url': 'https://example.org/book', 'title': '作者资料',
         'type': 'author', 'accessed_at': '2026-10-14',
         'excerpts': ['先记录问题，再比较两个方案。条件不明确时停止。']}]}


class TitleInputTests(unittest.TestCase):
    def test_old_yearbook_gets_new_module_without_changing_personal_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'year.html'
            path.write_text('<html><head></head><body><main><script id="reading-data">{"source_mode":"sample","books":["private book"]}</script><section id="ebook"><p>old module</p></section></main><script id="ebook-app-mounted">oldScript()</script></body></html>', 'utf8')
            page = workbench_page(yearbook=path)
            self.assertIn('ebookTitleInput', page)
            self.assertNotIn('oldScript()', page)
            self.assertTrue('{"source_mode":"sample","books":["private book"]}' in page)

    def test_title_creates_agent_handoff_without_fake_source_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, AgentRunner())
            try:
                self.assertTrue(hasattr(store, 'create_title'), '缺少网页书名入口')
                job = store.create_title('测试书', '测试作者', '检查流程')
                self.assertEqual(job['input_mode'], 'title')
                self.assertEqual(job['state'], 'awaiting_agent')
                self.assertEqual(job['book_query']['title'], '测试书')
                self.assertTrue(valid_saved_job(job, job['id']))
                self.assertFalse(list((store.jobs_dir / job['id']).glob('source.*')))
                store.action(job['id'], 'cancel')
                self.assertEqual(store.get(job['id'])['state'], 'cancelled')
                store.action(job['id'], 'retry')
                self.assertEqual(store.get(job['id'])['state'], 'awaiting_agent')
            finally:
                store.close()

    def test_title_input_and_cli_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, AgentRunner())
            try:
                self.assertTrue(hasattr(store, 'create_title'))
                for title in ('', 'a' * 201):
                    with self.assertRaises(ValueError): store.create_title(title)
                store.agent_mode = False
                with self.assertRaises(ValueError): store.create_title('测试书')
            finally: store.close()


class EvidenceTests(unittest.TestCase):
    def test_sources_preserve_exact_excerpt_and_metadata(self):
        module = library(self)
        doc = module.source_document(evidence(), {'id': 'b1', 'title': '测试书', 'author': '作者'}, 1)
        self.assertEqual(doc['elements'][0]['text'], evidence()['sources'][0]['excerpts'][0])
        self.assertEqual(doc['elements'][0]['source_type'], 'author')
        self.assertEqual(len(doc['source_hash']), 64)
        self.assertEqual(doc['bibliography'][0]['url'], 'https://example.org/book')
        self.assertNotIn('excerpts', doc['bibliography'][0])
        changed = evidence(); changed['sources'][0]['excerpts'][0] += '新增资料。'
        self.assertNotEqual(doc['source_hash'], module.source_document(changed, doc['book'] | {'id':'b1'}, 1)['source_hash'])

    def test_markdown_includes_shared_structure_and_scope(self):
        from ebook_pipeline import _render_outputs
        module = library(self)
        a = analysis_reply()
        a['book'].update(candidate())
        a['glossary'] = [{'term':'条件','definition':'输入的前提','sources':a['themes'][0]['sources'],'source_verified':True}]
        a.update(references=[],quality_status='needs_review',input_mode='title',source_notice=module.LABEL,
                 coverage={'scope_note':module.LABEL,'candidate_dispositions':[]})
        module.enrich(a, source_document_for_test(module), 'title')
        with tempfile.TemporaryDirectory() as tmp:
            _render_outputs(Path(tmp), a, {}, [], [], [])
            digest = (Path(tmp)/'DIGEST.md').read_text('utf8')
            self.assertIn('资料来源', digest)
            self.assertIn('https://example.org/book', digest)
            self.assertIn('章节／资料主题索引', digest)
            with self.subTest('book identity'): self.assertIn('版本：第一版', digest)
            glossary = (Path(tmp)/'GLOSSARY.md').read_text('utf8')
            with self.subTest('glossary scope'): self.assertIn('未核验全文', glossary)
            with self.subTest('glossary sources'): self.assertIn('https://example.org/book', glossary)

    def test_source_gate_rejects_wrong_book_empty_and_excess_budget(self):
        module = library(self); book = {'id':'b1','title':'书','author':'作者'}
        for change in ('wrong', 'empty', 'budget', 'marketing'):
            data = evidence()
            if change == 'wrong': data['sources'][0]['book_key'] = 'other'
            if change == 'empty': data['sources'] = []
            if change == 'budget': data['searches_used'] = 4
            if change == 'marketing': data['sources'][0]['excerpts'] = ['畅销好书']
            with self.assertRaises(ValueError): module.source_document(data, book, 1)

    def test_unsafe_source_urls_rejected_without_fetching(self):
        module = library(self)
        for url in ('http://127.0.0.1/book','http://[::1]/','file:///etc/passwd','https://user:pw@example.org/','http://localhost/a','javascript:alert(1)'):
            data = evidence(); data['sources'][0]['url'] = url
            with self.assertRaises(ValueError): module.source_document(data, {'id':'b1','title':'书','author':'作者'}, 0)

    def test_identity_not_found_and_ambiguity_cannot_guess(self):
        module = library(self)
        with self.assertRaises(ValueError): module.identities({'status':'not_found','candidates':[],'searches_used':1})
        with self.assertRaises(ValueError): module.identities({'status':'identified','candidates':[{'id':'a'},{'id':'b'}],'searches_used':1})

    def test_identity_must_match_requested_book(self):
        module = library(self)
        self.assertIn('query', inspect.signature(module.identities).parameters, '候选未绑定用户书名')
        found = {'status':'identified','candidates':[candidate()],'searches_used':1}
        with self.assertRaises(ValueError): module.identities(found, {'title':'另一书','author':''})
    def test_all_read_pages_count_including_identity(self):
        module = library(self)
        self.assertIn('identity_urls', inspect.signature(module.source_document).parameters, '身份页没有计入页面预算')
        data = evidence()
        data['sources'] = [{**data['sources'][0], 'id':'s'+str(i), 'url':'https://example.org/page'+str(i)} for i in range(8)]
        with self.assertRaises(ValueError): module.source_document(data, candidate(), 1, [candidate()['identity_url']])

    def test_decision_layer_links_existing_methods_without_inventing_rules(self):
        module = library(self)
        analysis = {'methods':[{'id':'m1','title':'检查','trigger':'条件明确时','steps':['记录'],
                   'boundaries':['条件不明停止'],'interpretation':'缩小问题','sources':[],
                   'verification':{'status':'needs_review'}}]}
        module.enrich(analysis, {'elements':[{'chapter':'第一章','element_id':'e1','location':'line 1'}]}, 'upload')
        self.assertEqual(analysis['decision_rules'][0]['method_id'], 'm1')
        self.assertEqual(analysis['decision_rules'][0]['boundaries'], ['条件不明停止'])
        self.assertEqual(analysis['structure_index'][0]['title'], '第一章')


def candidate(key='b1', author='作者'):
    return {'id':key,'title':'测试书','author':author,'edition':'第一版','identity_url':'https://example.org/book'}


def source_document_for_test(module):
    return module.source_document(evidence(), candidate(), 1)


def analysis_reply():
    source = {'element_id':'s1-1','quote':'先记录问题，再比较两个方案。','location':'作者资料'}
    return {'schema_version':1,'book':{'title':'测试书','author':'作者'},'overview':'先明确条件再选择方案。',
            'themes':[{'title':'记录与比较','explanation':'AI 解释：先收集条件再比较。','sources':[source]}],
            'methods':[],'cases':[],'counterexamples':[],'glossary':[],'limitations':['没有整书目录'], 'insights':[],
            'topic_coverage':[{'topic_id':'t1','status':'explained','item_refs':['themes:0'],'reason':'解释记录与比较'}]}


def review_reply():
    return {'status':'ready','reason':'','paragraphs':[{'text':'我在意先把条件弄清这一点。',
        'sources':analysis_reply()['themes'][0]['sources'],'quotes':[]}]}


class TitlePipelineTests(unittest.TestCase):
    def test_cancel_during_render_does_not_publish_formal_analysis(self):
        module = library(self)
        from ebook_pipeline import _render_outputs
        event = threading.Event()
        class Reader:
            def info(self): return {'mode':'current-agent-instructed-tools'}
            def prepare(self, stage, context, key): self.stage = stage
            def generate(self, *args, **kwargs):
                return {'title-identify':{'status':'identified','candidates':[candidate()],'searches_used':1},
                        'title-research':evidence(),'title-analysis':analysis_reply(),'reading-review':review_reply()}[self.stage]
            def commit(self, callback): callback()
        def render(*args):
            _render_outputs(*args); event.set()
        with tempfile.TemporaryDirectory() as tmp, patch('ebook_pipeline._render_outputs', side_effect=render):
            with self.assertRaises(InterruptedError): module.distill_title({'title':'测试书'}, tmp, Reader(), cancel_event=event)
            self.assertFalse((Path(tmp)/'analysis.json').exists())
    def test_public_result_is_never_full_book_and_bad_quote_never_published(self):
        module = library(self)
        self.assertTrue(hasattr(module, 'distill_title'), '书名分析管线尚未接通')
        class Reader:
            def info(self): return {'mode':'current-agent-instructed-tools','available':True,'execution_identity':{'session':'test'}}
            def prepare(self, stage, context, key): self.stage = stage
            def generate(self, prompt, **kwargs):
                if self.stage == 'title-identify': return {'status':'identified','candidates':[candidate()],'searches_used':1}
                if self.stage == 'title-research': return evidence()
                if self.stage == 'reading-review': return review_reply()
                result = analysis_reply()
                if self.bad: result['themes'][0]['sources'][0]['quote'] = '假的引文'
                return result
            def commit(self, callback): callback()
            def acknowledge(self, *args): pass
        with tempfile.TemporaryDirectory() as tmp:
            reader = Reader(); reader.bad = False
            data = module.distill_title({'title':'测试书','author':'作者'}, Path(tmp)/'good', reader)
            self.assertFalse(data['coverage']['full_text'])
            self.assertEqual(data['quality_status'], 'needs_review')
            self.assertEqual(data['book'].get('edition'), '第一版')
            self.assertIn('未核验全文', (Path(tmp)/'good/DIGEST.md').read_text('utf8'))
            self.assertEqual(data['themes'][0]['sources'][0]['source_type'], 'author')
            self.assertEqual(data['reading_status']['level'],'introduction')
            self.assertEqual(data['review']['status'],'ready')
            self.assertIn('我的书评', (Path(tmp)/'good/DIGEST.md').read_text('utf8'))
            reader.bad = True
            with self.assertRaises(ValueError): module.distill_title({'title':'测试书','author':'作者'}, Path(tmp)/'bad', reader)
            self.assertFalse((Path(tmp)/'bad/analysis.json').exists())

    def test_real_agent_waits_for_book_selection_before_research(self):
        library(self)
        with tempfile.TemporaryDirectory() as tmp:
            store = JobStore(tmp, AgentRunner())
            try:
                self.assertTrue(hasattr(store, 'select_book'), '同名选择尚未实现')
                job = store.create_title('测试书')
                store.agent_action(job['id'], 'claim', {'session':'s','host':'test','model':'unknown'})
                def pending():
                    for _ in range(200):
                        result = store.agent_action(job['id'], 'next', {'session':'s'})
                        if result['request']: return json.loads(Path(result['request']['request_path']).read_text('utf8'))
                        time.sleep(.005)
                    self.fail('阶段未生成')
                request = pending()
                self.assertEqual(request['stage'], 'title-identify')
                store.agent_action(job['id'], 'submit', {'session':'s','request_id':request['request_id'],
                    'answer':{'status':'ambiguous','candidates':[candidate(),candidate('b2','另一作者')],'searches_used':1}})
                for _ in range(200):
                    current = store.get(job['id'])
                    if current['state'] == 'needs_book_confirmation': break
                    time.sleep(.005)
                self.assertEqual(current['state'], 'needs_book_confirmation')
                with self.assertRaises(ValueError): store.select_book(job['id'], 'unknown')
                try: store.select_book(job['id'], [], current['selection_id'])
                except Exception as error: self.assertIsInstance(error, ValueError, '非法选择应返回输入错误，而非断开连接')
                else: self.fail('非法选择被接受')
                store.select_book(job['id'], 'b1', current['selection_id'])
                self.assertEqual(pending()['stage'], 'title-research')
                store.action(job['id'], 'cancel')
            finally: store.close()


if __name__ == '__main__': unittest.main()
