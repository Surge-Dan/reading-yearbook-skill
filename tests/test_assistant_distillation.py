import copy
import json
import sys
import tempfile
import threading
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'))
from test_ebook_core import ContractRunner
import ebook_pipeline as pipeline

KINDS=('framework','principle','case','counter-example','glossary')


class JointRunner(ContractRunner):
    def generate(self,prompt,schema=None,cancel_event=None):
        if 'OUTPUT_CONTRACT:joint-extraction' not in prompt:
            answer=super().generate(prompt,schema,cancel_event)
            if 'OUTPUT_CONTRACT:analysis' in prompt:
                answer['reading_lenses']=[{'id':'v1','kind':'values','title':'在意什么','text':'先检查输入。','sources':[self.source]}]
                answer['memorable_passages']=[{'text':self.source['quote'],'why_it_matters':'指向原文主题。','sources':[self.source]}]
            return answer
        self.calls.append(prompt)
        payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
        scans=[{'kind':kind,'scanned_chunk_ids':payload['chunk']['chunk_ids'],
                'scope_note':'已扫描本批全文，未找到其他本类候选。'} for kind in KINDS]
        candidates=[]
        if self.methods:
            candidates=[{'id':'c1','title':'检查法','type':'framework','summary':'逐项检查','task_ids':['t1'],'sources':[self.source]}]
        return {'candidates':candidates,'category_scans':scans,'gaps':[]}


class JointExtractionTests(unittest.TestCase):
    def run_pipeline(self,runner,root,**kwargs):
        source=Path(root)/'source.txt'; source.write_text('先检查输入，输入不全时停止，条件符合时执行检查。',encoding='utf-8')
        return pipeline.distill(source,Path(root)/'out',runner,**kwargs)

    def test_one_joint_extraction_with_all_categories_and_bundle(self):
        from distillation_result import load_bundle
        with tempfile.TemporaryDirectory() as tmp:
            runner=JointRunner(methods=True)
            result=self.run_pipeline(runner,tmp)
            extractions=[p for p in runner.calls if 'OUTPUT_CONTRACT:joint-extraction' in p]
            self.assertEqual(len(extractions),1,'Every batch needs one joint extraction')
            self.assertFalse(any('OUTPUT_CONTRACT:extraction' in p for p in runner.calls))
            self.assertIn('reading_lenses',next(p for p in runner.calls if 'OUTPUT_CONTRACT:analysis' in p))
            bundle=load_bundle(Path(tmp)/'out/distillation.json')
            self.assertEqual(bundle['analysis'],result)
            digest=(Path(tmp)/'out/DIGEST.md').read_text('utf-8')
            self.assertIn('在意什么',digest); self.assertIn('值得保留的金句',digest)
            count=len(runner.calls); self.run_pipeline(runner,tmp)
            self.assertEqual(len(runner.calls),count,'Unchanged source and rules must reuse accepted stages')

    def test_joint_contract_rejects_missing_scans_category_quote_and_cross_batch_ids(self):
        source={'element_id':'e1','quote':'原文','location':'line 1'}
        value={'candidates':[{'id':'c1','title':'规则','type':'framework','summary':'规则说明','task_ids':[],'sources':[source]}],
               'category_scans':[{'kind':kind,'scanned_chunk_ids':['ch1'],'scope_note':'已扫描，无其他候选'} for kind in KINDS],'gaps':[]}
        payload={'chunk':{'chunk_ids':['ch1'],'elements':[{'element_id':'e1','text':'原文','location':'line 1'}]}}
        self.assertEqual(pipeline._stage_contract('extract-joint-v1',copy.deepcopy(value),payload),value)
        for change in ('scan','missing','kind','id'):
            broken=copy.deepcopy(value)
            if change=='scan': broken['category_scans'][0]['scanned_chunk_ids']=[]
            if change=='missing': broken['category_scans'].pop()
            if change=='kind': broken['candidates'][0]['type']='invented'
            if change=='id': broken['candidates']*=2
            with self.subTest(change=change),self.assertRaises(ValueError): pipeline._stage_contract('extract-joint-v1',broken,payload)
        with tempfile.TemporaryDirectory() as tmp:
            source_path=Path(tmp)/'two.txt';source_path.write_text(('原文检查。'*2500)+'\n\n'+('原文检查。'*2500),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'ID 重复'):
                pipeline.distill(source_path,Path(tmp)/'out',JointRunner(methods=True))

    def test_budget_uses_two_calls_per_batch_and_failure_archives_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.run_pipeline(JointRunner(),tmp)
            self.assertTrue((Path(tmp)/'out/distillation.json').is_file())
            event=threading.Event();event.set()
            with self.assertRaises(InterruptedError): self.run_pipeline(JointRunner(),tmp,cancel_event=event)
            self.assertFalse((Path(tmp)/'out/distillation.json').exists())
            self.assertTrue(list((Path(tmp)/'out/.history').glob('*/distillation.json')))
            source=Path(tmp)/'large.txt';source.write_text('检查原文。'*21000,encoding='utf-8')
            with self.assertRaises(pipeline.BudgetRequired) as caught: pipeline.distill(source,Path(tmp)/'large',JointRunner())
            estimate=caught.exception.estimate
            self.assertEqual(estimate['minimum_model_calls'],estimate['model_batches']*2+6)

    def test_legacy_five_category_cache_reuses_understanding_but_not_joint_extraction(self):
        namespace={'__file__':pipeline.__file__,'__name__':'legacy_pipeline'}
        source=subprocess.check_output(['git','show','dfbea095e843d296a9e212a8172a11dd76a65da5:reading-yearbook-skill/scripts/ebook_pipeline.py']).decode('utf-8')
        exec(compile(source,'legacy_pipeline','exec'),namespace)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'source.txt';path.write_text('受控短篇正文。',encoding='utf-8');out=Path(tmp)/'out'
            namespace['distill'](path,out,ContractRunner())
            runner=JointRunner();runner.source={'element_id':'e0000001','quote':'受控短篇正文。','location':'line 1'}
            pipeline.distill(path,out,runner)
            self.assertFalse(any('OUTPUT_CONTRACT:stage0' in p for p in runner.calls))
            self.assertEqual(sum('OUTPUT_CONTRACT:joint-extraction' in p for p in runner.calls),1)
            original=pipeline._rules;count=len(runner.calls)
            def changed(*paths):
                return original(*paths)+('\nNew joint extraction rule.' if any(p.startswith('extractors/') for p in paths) else '')
            with patch('ebook_pipeline._rules',changed):pipeline.distill(path,out,runner)
            self.assertEqual(len(runner.calls)-count,1)
            self.assertIn('OUTPUT_CONTRACT:joint-extraction',runner.calls[-1])

    def test_joint_bad_quote_rejected_before_cache_or_bundle(self):
        class Bad(JointRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:result['candidates'][0]['sources'][0]['quote']='虚构引文'
                return result
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):self.run_pipeline(Bad(methods=True),tmp)
            self.assertFalse((Path(tmp)/'out/distillation.json').exists())
            self.assertFalse(any('category_scans' in p.read_text('utf-8') for p in (Path(tmp)/'out/.cache').glob('*.json')))

    def test_final_publication_commit_failure_removes_active_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            out=Path(tmp)/'out'
            class Expired(JointRunner):
                def commit(self,callback):
                    callback()
                    if (out/'distillation.json').exists():raise InterruptedError('lease expired at final commit')
            with self.assertRaises(InterruptedError):self.run_pipeline(Expired(),tmp)
            self.assertFalse((out/'distillation.json').exists())


class TitleBundleTests(unittest.TestCase):
    def test_title_publishes_bundle_and_failed_retry_removes_active_result(self):
        import ebook_title
        from test_book_title import candidate,evidence,analysis_reply,review_reply
        class Reader:
            bad=False
            def info(self):return {'mode':'current-agent-instructed-tools','available':True}
            def prepare(self,stage,context,key):self.stage=stage
            def generate(self,prompt,**kwargs):
                if self.stage=='title-analysis':
                    self.analysis_prompt=prompt
                    value=analysis_reply()
                    if self.bad:value['themes'][0]['sources'][0]['quote']='虚构引文'
                    return value
                return {'title-identify':{'status':'identified','candidates':[candidate()],'searches_used':1},
                        'title-research':evidence(),'reading-review':review_reply()}[self.stage]
        with tempfile.TemporaryDirectory() as tmp:
            runner=Reader()
            ebook_title.distill_title({'title':'测试书'},tmp,runner)
            self.assertTrue((Path(tmp)/'distillation.json').exists())
            self.assertIn('reading_lenses',runner.analysis_prompt)
            runner.bad=True
            with self.assertRaises(ValueError):ebook_title.distill_title({'title':'测试书'},tmp,runner,focus='changed')
            self.assertFalse((Path(tmp)/'distillation.json').exists())

    def test_title_commit_failure_cannot_leave_formal_bundle(self):
        import ebook_title
        from test_book_title import candidate,evidence,analysis_reply,review_reply
        with tempfile.TemporaryDirectory() as tmp:
            class Expired:
                def info(self):return {'mode':'current-agent-instructed-tools','available':True}
                def prepare(self,stage,context,key):self.stage=stage
                def generate(self,*args,**kwargs):
                    return {'title-identify':{'status':'identified','candidates':[candidate()],'searches_used':1},
                        'title-research':evidence(),'title-analysis':analysis_reply(),'reading-review':review_reply()}[self.stage]
                def commit(self,callback):
                    callback()
                    if (Path(tmp)/'distillation.json').exists():raise InterruptedError('lease expired at final commit')
            with self.assertRaises(InterruptedError):ebook_title.distill_title({'title':'测试书'},tmp,Expired())
            self.assertFalse((Path(tmp)/'distillation.json').exists())


if __name__=='__main__':unittest.main()
