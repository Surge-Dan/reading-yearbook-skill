import importlib
import sys
import tempfile
import unittest
import threading
import zipfile
import json
from unittest.mock import patch
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))

class ContractRunner:
    """Controlled model fixture: validates orchestration, never a live book claim."""
    def __init__(self, methods=False, gaps=False, wrong_routing=False):
        self.calls=[]; self.methods=methods; self.gaps=gaps; self.wrong_routing=wrong_routing
    def info(self): return {'name':'contract-fixture','available':True}
    def generate(self,prompt,schema=None,cancel_event=None):
        self.calls.append(prompt)
        payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
        source={'element_id':'e0000001','quote':'原文','location':'line 1'}
        if 'chunk' in payload:
            element=payload['chunk']['elements'][0]
            source={k:element[k] for k in ('element_id','location')}; source['quote']=element['text'][:20].strip()
            self.source=source
        source=getattr(self,'source',source)
        theme={'title':'人物与时代','explanation':'叙事主题','sources':[source]}
        task={'id':'t1','title':'核查输入','sources':[source]}
        candidate={'id':'c1','title':'检查法','type':'framework','summary':'逐项检查','task_ids':['t1'],'sources':[source]}
        method={'id':'m1','candidate_ids':['c1'],'title':'检查法','interpretation':'AI 对原书规则的解释','trigger':'需要检查时','steps':['check'],'example':'原书未给案例，合成演练','boundaries':['信息不足先询问'],'sources':[source],'verification':{'status':'validated','V1':True,'V2':True,'V3':True,'source_sufficiency':{'reason':'complete rule'},'walkthrough':{'input':'x','steps':['check'],'output':'y'},'task_utility':'check omissions'}}
        gaps=['未读到关键条件'] if self.gaps else []
        if 'OUTPUT_CONTRACT:stage0' in prompt:
            return {'summary':'原书骨架','genre':'methodology' if self.methods else 'literary','scope_note':'基于所有正文批次识别主题与适用范围','themes':[theme],'key_tasks':[task] if self.methods or self.gaps else [],'gaps':gaps}
        if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
            return {'candidates':[candidate] if self.methods else [],'category_scans':[
                {'kind':kind,'scanned_chunk_ids':payload['chunk']['chunk_ids'],'scope_note':'全批次扫描完成，无其他本类候选'}
                for kind in ('framework','principle','case','counter-example','glossary')],'gaps':gaps}
        if 'OUTPUT_CONTRACT:extraction' in prompt:
            return {'candidates':[candidate] if self.methods and payload['extractor_kind']=='framework' else [],'scanned_chunk_ids':payload['chunk']['chunk_ids'],'scope_note':'全批次扫描完成，无其他本类候选','gaps':gaps}
        if 'OUTPUT_CONTRACT:batched-v1-alignment' in prompt:
            return {'groups':[{'candidate_ids':[c['id']],'canonical_id':c['id'],'reason':'独立机制，未证明重复'} for c in payload['catalog']],'gaps':gaps}
        if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
            return {'candidates':[dict(c,status='validated' if c['id']=='c1' else 'reference',reason='来源充分并完成演练',verification=dict(method['verification'],walkthrough=dict(method['verification']['walkthrough'],completion_standard='无遗漏'))) for c in payload['candidates'] if c['id'] in payload['assigned_ids']],'gaps':gaps}
        if 'OUTPUT_CONTRACT:batched-v1-global' in prompt:
            return {'adjustments':[],'task_audit':[{'task_id':t['id'],'status':'covered' if self.methods else 'reference' if payload['catalog'] else 'missing','candidate_ids':['c1'] if self.methods else [payload['catalog'][0]['id']] if payload['catalog'] else [],'reason':'逐项核查'} for t in payload['overview']['key_tasks']],'gaps':gaps}
        if 'OUTPUT_CONTRACT:verification' in prompt:
            return {'candidates':[dict(candidate,status='validated',reason='来源充分并完成演练')] if self.methods else [],'task_audit':[{'task_id':'t1','status':'covered' if self.methods else 'missing','candidate_ids':['c1'] if self.methods else [],'reason':'逐项核查'}] if self.methods or self.gaps else [],'gaps':gaps}
        if 'OUTPUT_CONTRACT:ria' in prompt or 'OUTPUT_CONTRACT:organization' in prompt:
            return {'cards':[dict(method,candidate_id='c1')] if self.methods else [],'themes':[theme],'scope_note':'文学内容保留主题，不硬造方法','relations':[],'gaps':gaps}
        if 'OUTPUT_CONTRACT:analysis\n' in prompt:
            theme['sources']=[s for t in payload.get('content_map',[]) for s in t['sources']] or [source]
            return {'schema_version':1,'book':{'title':'T','author':''},'overview':'原书主题与边界','themes':[theme],'methods':[method] if self.methods else [],'cases':[],'counterexamples':[],'glossary':[],'limitations':[], 'insights':[],
                    'topic_coverage':[{'topic_id':t['id'],'status':'explained','item_refs':['themes:0'],'reason':'解释了实际材料'} for t in payload.get('content_map',[])]}
        if 'OUTPUT_CONTRACT:reading_review' in prompt:
            return {'status':'ready','reason':'','paragraphs':[{'text':'我更在意先检查信息这个选择。','sources':[source],'quotes':[]}]}
        if 'OUTPUT_CONTRACT:pressure_suite' in prompt:
            return {'test_cases':[{'id':k,'method_id':'m1','kind':k,'expected_routing':'m1' if k in ('normal','missing_input') else 'none','task':'Perform '+k,'input':{},'checks':['result correct']} for k in ('normal','missing_input','negative','adjacent')]}
        if 'OUTPUT_CONTRACT:baseline_results' in prompt or 'OUTPUT_CONTRACT:execution_results' in prompt:
            return {'results':[{'case_id':k,'answer':'实际完成输出','chosen_method':'m1' if self.wrong_routing or k in ('normal','missing_input') else 'none'} for k in ('normal','missing_input','negative','adjacent')]}
        if 'OUTPUT_CONTRACT:judgment_results' in prompt:
            return {'results':[{'case_id':k,'passed':True,'baseline_passed':True,'reasons':['criteria match'],'check_results':[{'check':'result correct','passed':True}]} for k in ('normal','missing_input','negative','adjacent')]}
        raise AssertionError('Unknown contract')

class CoreTests(unittest.TestCase):
    def module(self, name):
        try: return importlib.import_module(name)
        except ImportError: self.fail('Missing required module ' + name)

    def test_long_paragraph_and_last_chapter_are_preserved(self):
        m = self.module('ebook_document')
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'book.md'; p.write_text('# First\n' + '甲'*19000 + '\n# Last\n末章证据', encoding='utf-8')
            doc = m.parse_document(p)
            chunks = m.build_chunks(doc, max_chars=3000)
            self.assertEqual(''.join(e['text'] for e in doc['elements']), ''.join(e['text'] for c in chunks for e in c['elements']))
            self.assertIn('末章证据', chunks[-1]['elements'][-1]['text'])
            self.assertEqual(doc['source_hash'], m.parse_document(p)['source_hash'])

    def test_literary_pipeline_runs_all_stages_and_reuses_cache(self):
        m = self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'novel.txt'; p.write_text('人物在河边回忆童年。', encoding='utf-8'); r=ContractRunner()
            result=m.distill(p,Path(d)/'out',r)
            self.assertEqual(result['methods'],[]); self.assertTrue(result['coverage']['complete'])
            self.assertEqual(len(r.calls),8)
            count=len(r.calls); m.distill(p,Path(d)/'out',r); self.assertEqual(count,len(r.calls))
            self.assertTrue((Path(d)/'out/DIGEST.md').exists())

    def test_budget_gate_precedes_ai(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'large.txt'; p.write_text('字'*200000,encoding='utf-8')
            with self.assertRaises(m.BudgetRequired): m.distill(p,Path(d)/'out',None)

    def test_runner_rejects_non_json(self):
        m=self.module('ebook_runner')
        with self.assertRaises(ValueError): m.parse_json('Here is an answer {"x":1}')
        self.assertEqual(m.parse_json('{"x":1}'), {'x':1})

    def test_epub_spine_order_and_archive_safety(self):
        m=self.module('ebook_document')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'book.epub'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('META-INF/container.xml','<container><rootfile full-path="book.opf"/></container>')
                z.writestr('book.opf','<package xmlns="urn:test"><metadata><title>原书元数据</title></metadata><manifest><item id="a" href="a.xhtml"/><item id="b" href="b.xhtml"/></manifest><spine><itemref idref="b"/><itemref idref="a"/></spine></package>')
                z.writestr('a.xhtml','<p>first</p>'); z.writestr('b.xhtml','<p>second</p>')
            doc=m.parse_document(p); self.assertEqual(doc['elements'][0]['text'],'second\n')
            pipeline=self.module('ebook_pipeline')
            result=pipeline.distill(p,Path(d)/'out',ContractRunner(),source_name='上传文件名.epub')
            self.assertEqual(result['book']['title'],'原书元数据')
            with zipfile.ZipFile(p,'a') as z: z.writestr('../escape','bad')
            with self.assertRaisesRegex(ValueError,'Unsafe'): m.parse_document(p)

    def test_epub_skips_only_declared_nav_and_gutenberg_wrappers(self):
        m=self.module('ebook_document')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.epub'
            with zipfile.ZipFile(p,'w') as z:
                z.writestr('META-INF/container.xml','<container><rootfile full-path="book.opf"/></container>')
                z.writestr('book.opf','<package xmlns="urn:test"><manifest><item id="nav" href="nav.xhtml" properties="nav"/><item id="body" href="body.xhtml"/></manifest><spine><itemref idref="nav"/><itemref idref="body"/></spine></package>')
                z.writestr('nav.xhtml','<p>Navigation noise</p>')
                z.writestr('body.xhtml','<header id="pg-header">  <div><p>Gutenberg metadata</p></div> </header> <header>作者序言</header><p>完整正文</p><footer id="pg-footer"><div><p>license</p></div></footer><p>末段</p>')
            doc=m.parse_document(p); text=''.join(e['text'] for e in doc['elements'])
            self.assertNotIn('Navigation noise',text); self.assertNotIn('Gutenberg metadata',text); self.assertNotIn('license',text)
            self.assertIn('作者序言',text); self.assertIn('完整正文',text); self.assertIn('末段',text)
            self.assertEqual(len(doc['exclusions']),3); self.assertEqual(doc['warnings'],[])

    def test_bad_source_never_validated(self):
        m=self.module('ebook_pipeline')
        doc={'elements':[{'element_id':'e1','text':'真实原文','location':'line 1'}]}
        data={'themes':[],'methods':[{'title':'伪造','sources':[{'element_id':'e1','quote':'不存在'}],'verification':{'status':'validated'}}],'cases':[],'counterexamples':[],'glossary':[]}
        self.assertEqual(m._validate_sources(data,doc),['伪造'])
        self.assertEqual(data['methods'][0]['verification']['status'],'needs_review')

    def test_cancel_precedes_work(self):
        m=self.module('ebook_pipeline'); event=threading.Event(); event.set()
        with self.assertRaises(InterruptedError): m.distill('does-not-exist', 'out',None,cancel_event=event)

    def test_manifest_verifies_vendored_resources(self):
        m=self.module('ebook_pipeline'); manifest=m.upstream_manifest()
        self.assertEqual(manifest['commit'],'a28de55ba881b9928956a55048f743f7a9e3b23e')
        self.assertGreater(len(manifest['files']),10)

    def test_failed_retry_removes_formal_completion(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'; out.mkdir(); (out/'analysis.json').write_text('{"quality_status":"completed"}')
            p=Path(d)/'empty.txt'; p.write_text('')
            with self.assertRaises(ValueError): m.distill(p,out,None)
            self.assertFalse((out/'analysis.json').exists())

    def test_empty_stage_is_rejected_before_cache(self):
        m=self.module('ebook_pipeline')
        class Empty(ContractRunner):
            def generate(self,*args,**kwargs): return {}
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); out=Path(d)/'out'
            with self.assertRaises(ValueError): m.distill(p,out,Empty())
            self.assertEqual(list((out/'.cache').glob('*.json')),[])

    def test_fabricated_intermediate_quote_is_rejected_before_cache(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:stage0' in prompt: result['themes'][0]['sources'][0]['quote']='不存在的引用'
                return result
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); out=Path(d)/'out'
            with self.assertRaises(ValueError): m.distill(p,out,Runner())
            self.assertEqual(list((out/'.cache').glob('*.json')),[])

    def test_gaps_and_unresolved_key_tasks_block_completion(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8')
            result=m.distill(p,Path(d)/'out',ContractRunner(gaps=True))
            self.assertFalse(result['coverage']['complete'])
            self.assertEqual(result['quality_status'],'needs_review')
            self.assertEqual(result['coverage']['task_audit'][0]['status'],'missing')

    def test_negative_route_cannot_validate_even_when_judge_says_pass(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8')
            result=m.distill(p,Path(d)/'out',ContractRunner(methods=True,wrong_routing=True))
            self.assertEqual(result['methods'][0]['verification']['status'],'needs_review')
            self.assertFalse(result['coverage']['complete'])

    def test_failed_retry_archives_all_owned_outputs(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'; out.mkdir(); (out/'DIGEST.md').write_text('状态：completed'); (out/'methods').mkdir(); (out/'methods/old.md').write_text('validated')
            p=Path(d)/'empty.txt'; p.write_text('')
            with self.assertRaises(ValueError): m.distill(p,out,None)
            self.assertFalse((out/'DIGEST.md').exists()); self.assertFalse((out/'methods').exists())
            self.assertTrue(list((out/'.history').rglob('old.md')))

    def test_archive_rejects_redirected_history_before_moving_any_output(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'; out.mkdir(); outside=Path(d)/'outside'; outside.mkdir()
            (out/'analysis.json').write_text('completed'); (out/'DIGEST.md').write_text('completed')
            original=Path.is_symlink
            with patch.object(Path,'is_symlink',lambda path: True if path==out/'.history' else original(path)):
                with self.assertRaises(ValueError): m._archive_generation(out)
            self.assertTrue((out/'analysis.json').exists()); self.assertTrue((out/'DIGEST.md').exists())
            self.assertFalse((out/'.history').exists()); self.assertEqual(list(outside.iterdir()),[])

    def test_archive_rejects_resolved_junction_escape_before_mkdir(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'; out.mkdir(); outside=Path(d)/'outside'; outside.mkdir()
            (out/'analysis.json').write_text('completed'); original=Path.resolve
            with patch.object(Path,'resolve',lambda path,*a,**k: outside if path==out/'.history' else original(path,*a,**k)):
                with self.assertRaises(ValueError): m._archive_generation(out)
            self.assertTrue((out/'analysis.json').exists()); self.assertFalse((out/'.history').exists())

    def test_archive_checks_late_owned_link_before_moving_earlier_files(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'out'; out.mkdir(); (out/'analysis.json').write_text('completed'); (out/'methods').mkdir()
            original=Path.is_symlink
            with patch.object(Path,'is_symlink',lambda path: True if path==out/'methods' else original(path)):
                with self.assertRaises(ValueError): m._archive_generation(out)
            self.assertTrue((out/'analysis.json').exists()); self.assertFalse((out/'.history').exists())

    def test_reference_candidates_are_delivered_with_summary_and_sources(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates']=[{'id':'r1','title':'参考原则','type':'principle','summary':'有来源但缺乏独立执行步骤的参考解释','task_ids':[],'sources':[self.source]}]
                if 'OUTPUT_CONTRACT:stage0' in prompt: result['key_tasks']=[{'id':'t1','title':'理解参考原则','sources':[self.source]}]
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    result['candidates']=[{'id':'r1','status':'reference','reason':'有阅读价值但无可执行步骤','task_ids':['t1'],'sources':[self.source]}]
                    result['candidates'][0]['task_ids']=[]
                return result
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); out=Path(d)/'out'
            analysis=m.distill(p,out,Runner())
            self.assertEqual(analysis['references'][0]['summary'],'有来源但缺乏独立执行步骤的参考解释')
            self.assertEqual(analysis['references'][0]['sources'][0]['quote'],'原文')
            self.assertEqual(analysis['coverage']['task_audit'][0]['status'],'reference')
            self.assertTrue(analysis['coverage']['complete'])
            text=(out/'DIGEST.md').read_text(encoding='utf-8')
            self.assertIn('参考原则',text); self.assertIn('有来源但缺乏独立执行步骤的参考解释',text)

    def test_reference_task_rejects_rejected_and_mixed_candidate_mappings(self):
        m=self.module('ebook_pipeline')
        source={'element_id':'e1','quote':'原文','location':'line 1'}
        payload={'overview':{'key_tasks':[{'id':'t1'}]},'all_extractions':{'principle':[{'candidates':[{'id':'r1'},{'id':'x1'}]}]}}
        candidates=[{'id':'r1','status':'reference','reason':'参考材料','task_ids':['t1'],'sources':[source]},
                    {'id':'x1','status':'rejected','reason':'无价值','task_ids':['t1'],'sources':[source]}]
        for ids in (['x1'],['r1','x1']):
            with self.subTest(ids=ids):
                value={'candidates':candidates,'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':ids,'reason':'参考覆盖'}],'gaps':[]}
                with self.assertRaises(ValueError): m._stage_contract('triple-verification',value,payload)

    def test_reference_coverage_requires_every_candidate_to_be_delivered(self):
        m=self.module('ebook_pipeline')
        disposition=[{'id':'r1','final_status':'reference'},{'id':'r2','final_status':'reference'},{'id':'x1','final_status':'rejected'}]
        for ids,delivered,expected in [(['r1'],['r1'],'reference'),(['r1'],[],'needs_review'),(['r1','r2'],['r1'],'needs_review'),(['r1','x1'],['r1'],'needs_review')]:
            with self.subTest(ids=ids,delivered=delivered):
                tasks=[{'task_id':'t1','status':'reference','candidate_ids':ids,'reason':'参考覆盖'}]
                m._reconcile_task_audit(tasks,disposition,[{'id':cid} for cid in delivered])
                self.assertEqual(tasks[0]['status'],expected)

    def test_duplicate_extraction_ids_fail_before_verification(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates'].append({'id':'c1','title':'另一原则','type':'principle','summary':'不同候选','task_ids':['t1'],'sources':[self.source]})
                return result
        for text in ('原文','原文'*7000):
            with self.subTest(scope='category' if len(text)==2 else 'batch'),tempfile.TemporaryDirectory() as d:
                p=Path(d)/'b.txt'; p.write_text(text,encoding='utf-8'); runner=Runner(methods=True)
                with self.assertRaisesRegex(ValueError,'候选 ID|契约'):
                    m.distill(p,Path(d)/'out',runner)
                self.assertFalse(any('OUTPUT_CONTRACT:verification' in call for call in runner.calls))
                # Reused extraction replies must go through the same global gate.
                with self.assertRaisesRegex(ValueError,'候选 ID|契约'):
                    m.distill(p,Path(d)/'out',runner)
                self.assertFalse(any('OUTPUT_CONTRACT:verification' in call for call in runner.calls))

    def test_digest_is_self_contained_with_steps_and_source_anchors(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); out=Path(d)/'out'
            m.distill(p,out,ContractRunner(methods=True))
            text=(out/'DIGEST.md').read_text(encoding='utf-8')
            self.assertIn('1. check',text); self.assertIn('e0000001',text); self.assertIn('AI',text)
            self.assertNotIn('(methods/',text)

    def test_duplicate_extraction_retry_reuses_valid_stages_after_correction(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            corrected=False
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates'].append({'id':'r2' if self.corrected else 'c1','title':'另一原则','type':'principle','summary':'不同候选','task_ids':[],'sources':[self.source]})
                if 'OUTPUT_CONTRACT:verification' in prompt:
                    result['candidates'].append({'id':'r2','status':'reference','reason':'仅作参考','task_ids':[],'sources':[self.source]})
                return result
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); runner=Runner(methods=True); out=Path(d)/'out'
            with self.assertRaisesRegex(ValueError,'候选 ID|契约'): m.distill(p,out,runner)
            files=list((out/'.cache').glob('*.json'))
            conflict=[f for f in files if any(c.get('title')=='另一原则' for c in json.loads(f.read_text('utf-8')).get('candidates',[]))]
            valid={f.name:f.read_bytes() for f in files if f not in conflict}
            with self.subTest(phase='invalid output is not valid cache'): self.assertEqual(conflict,[])
            runner.corrected=True
            result=m.distill(p,out,runner)
            self.assertEqual(result['quality_status'],'completed')
            self.assertEqual(result['references'][0]['id'],'r2')
            self.assertEqual(len([call for call in runner.calls if 'OUTPUT_CONTRACT:stage0' in call]),2)
            self.assertEqual(sum('OUTPUT_CONTRACT:joint-extraction' in call for call in runner.calls),2)
            self.assertEqual({name:(out/'.cache'/name).read_bytes() for name in valid},valid)
            # Simulate a conflicting cache written by the previous implementation.
            principle=next(f for f in (out/'.cache').glob('*.json') if any(c.get('title')=='另一原则' for c in json.loads(f.read_text('utf-8')).get('candidates',[])))
            legacy=json.loads(principle.read_text('utf-8')); legacy['candidates'][1]['id']='c1'
            principle.write_text(json.dumps(legacy,ensure_ascii=False),encoding='utf-8')
            calls_before=len(runner.calls)
            self.assertEqual(m.distill(p,out,runner)['quality_status'],'completed')
            self.assertEqual(len(runner.calls),calls_before+1)
            self.assertEqual(json.loads(principle.read_text('utf-8'))['candidates'][1]['id'],'r2')
            self.assertEqual({name:(out/'.cache'/name).read_bytes() for name in valid},valid)

    def test_pressure_cache_retries_after_invalid_plan(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            invalid=True
            def generate(self,prompt,*args,**kwargs):
                if self.invalid and 'OUTPUT_CONTRACT:pressure_suite' in prompt: return {'test_cases':[]}
                return super().generate(prompt,*args,**kwargs)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); out=Path(d)/'out'; r=Runner(methods=True)
            with self.assertRaises(ValueError): m.distill(p,out,r)
            r.invalid=False
            self.assertEqual(m.distill(p,out,r)['quality_status'],'completed')

    def test_progress_announces_stage_before_call_without_advancing_count(self):
        m=self.module('ebook_pipeline'); runner=ContractRunner(); updates=[]
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8')
            m.distill(p,Path(d)/'out',runner,progress=lambda item: updates.append((dict(item),len(runner.calls))))
        self.assertEqual(updates[0][0]['stage'],'stage0-map'); self.assertEqual(updates[0][0]['completed'],0); self.assertEqual(updates[0][1],0)

    def test_claude_structured_output_envelope_is_consumed(self):
        m=self.module('ebook_runner')
        self.assertEqual(m.parse_claude_output('{"result":"not JSON","structured_output":{"ready":true}}'),{'ready':True})

    def test_vendor_manifest_accepts_platform_line_endings(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            dest=Path(d)/'vendor'
            import shutil
            shutil.copytree(m.UPSTREAM,dest)
            target=dest/'methodology/01-stage0-adler.md'
            target.write_bytes(target.read_bytes().replace(b'\r\n',b'\n').replace(b'\n',b'\r\n'))
            with patch.object(m,'UPSTREAM',dest): self.assertEqual(m.upstream_manifest()['hash_kind'],'text-lf')

    def test_malformed_source_entries_raise_value_error(self):
        m=self.module('ebook_pipeline')
        data={'themes':[{'title':'T','explanation':'E','sources':['not-an-object']}], 'methods':[],'cases':[],'counterexamples':[],'glossary':[],'limitations':[],'schema_version':1,'book':{'title':'T','author':''},'overview':'O'}
        with self.assertRaises(ValueError): m._analysis_contract(data)

    def test_chinese_quote_limit_is_enforced(self):
        m=self.module('ebook_pipeline'); quote='书'*151
        doc={'elements':[{'element_id':'e1','text':quote,'location':'line 1'}]}
        data={'themes':[],'methods':[{'title':'T','sources':[{'element_id':'e1','quote':quote}], 'verification':{}}],'cases':[],'counterexamples':[],'glossary':[]}
        self.assertEqual(m._validate_sources(data,doc),['T'])

    def test_pressure_trials_use_real_batch_outputs_and_matching_ids(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('原文',encoding='utf-8'); r=ContractRunner(methods=True)
            result=m.distill(p,Path(d)/'out',r)
            self.assertEqual(len(r.calls),14)  # One joint extraction and the cached reading review.
            self.assertEqual(result['methods'][0]['verification']['status'],'validated')

    def test_short_chapters_are_batched_without_cost_pause(self):
        m=self.module('ebook_pipeline')
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.md'; p.write_text('\n'.join('# Chapter '+str(i)+'\n'+'字'*100 for i in range(13)),encoding='utf-8'); r=ContractRunner()
            result=m.distill(p,Path(d)/'out',r)
            self.assertEqual(result['coverage']['chunks_total'],13)
            self.assertEqual(len(r.calls),8)  # One bounded review and one joint extraction.

    def test_invalid_final_output_is_not_reused_as_valid_cache(self):
        m=self.module('ebook_pipeline')
        class Runner(ContractRunner):
            valid=False
            def generate(self,prompt,schema=None,cancel_event=None):
                if 'OUTPUT_CONTRACT:analysis\n' in prompt:
                    if not self.valid: return {'schema_version':1}
                return super().generate(prompt,schema,cancel_event)
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'b.txt'; p.write_text('正文',encoding='utf-8'); r=Runner(); out=Path(d)/'out'
            with self.assertRaises(ValueError): m.distill(p,out,r)
            r.valid=True
            self.assertEqual(m.distill(p,out,r)['quality_status'],'completed')

if __name__ == '__main__': unittest.main()
