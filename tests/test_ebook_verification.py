import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'))

class VerificationTests(unittest.TestCase):
    def test_new_global_cross_batch_relation_requires_full_records_and_cited_evidence(self):
        import copy
        import ebook_verification as v
        candidates=[self.candidate('c1','e1'),self.candidate('c2','e2')]
        alignment={'groups':[{'candidate_ids':[c['id']],'canonical_id':c['id'],'reason':'独立待核'} for c in candidates]}
        document={'elements':[{'element_id':'e1','text':'原文条件一'},{'element_id':'e2','text':'原文条件二'}]}
        packages=[v.evidence_package([c['id']],candidates,alignment,document,[]) for c in candidates]
        batches=[v.validate_batch({'candidates':[dict(p['candidates'][0],status='reference',reason='保留参考')],'gaps':['本批限制']},p) for p in packages]
        closing={'adjustments':[{'id':'c2','status':'rejected','reason':'同一机制','canonical_id':'c1','coverage_reason':'输入、执行、条件和收益均被完整覆盖'}],'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':['c1'],'reason':'实际保留代表'}],'gaps':['全局限制']}
        evidence=v.evidence_package(['c1','c2'],candidates,alignment,document,[])
        result=v.merge_verification(candidates,batches,closing,{'key_tasks':[{'id':'t1'}]},['原始限制'],evidence,document)
        self.assertEqual(result['candidates'][0]['original_candidate_ids'],['c1','c2'])
        self.assertEqual(result['candidates'][0]['sources'],candidates[0]['sources']+candidates[1]['sources'])
        self.assertEqual(result['gaps'],['原始限制','本批限制','全局限制'])
        for field in ('summary','task_ids','sources'):
            incomplete=copy.deepcopy(evidence); incomplete['candidates'][1].pop(field)
            with self.subTest(field=field),self.assertRaises(ValueError): v.merge_verification(candidates,batches,closing,{'key_tasks':[{'id':'t1'}]},[],incomplete,document)
        missing=copy.deepcopy(evidence); missing['evidence_elements'][1]['text']='原文'
        with self.assertRaises(ValueError): v.merge_verification(candidates,batches,closing,{'key_tasks':[{'id':'t1'}]},[],missing,document)

    def test_cross_batch_same_mechanism_merges_but_similar_titles_remain(self):
        import ebook_verification as v
        candidates=[self.candidate('c'+str(i),'e'+str(i)) for i in range(17)]
        candidates[0]['summary']=candidates[16]['summary']='固定输入逐项检查机制'
        candidates[1]['summary']='基于变化趋势提前预警机制'
        alignment={'groups':[{'candidate_ids':['c0','c16'],'canonical_id':'c0','reason':'同一检查机制'}]+[{'candidate_ids':['c'+str(i)],'canonical_id':'c'+str(i),'reason':'不同机制'} for i in range(1,16)]}
        document={'elements':[{'element_id':'e'+str(i),'text':'原文'} for i in range(17)]}
        packages=v.verification_batches(candidates,alignment,document,[])
        self.assertEqual([len(p['assigned_ids']) for p in packages],[16,1])
        batches=[]
        for package in packages:
            decisions=[dict(c,status='reference',reason='独立机制保留') for c in package['candidates'] if c['id'] in package['assigned_ids']]
            for row in decisions:
                if row['id']=='c16': row.update(status='rejected',canonical_id='c0',coverage_reason='相同检查输入、步骤、条件和结果完整覆盖')
            batches.append(v.validate_batch({'candidates':decisions,'gaps':[]},package))
        closing={'adjustments':[],'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':['c0','c1'],'reason':'两种不同机制保留'}],'gaps':[]}
        result=v.merge_verification(candidates,batches,closing,{'key_tasks':[{'id':'t1'}]},[])
        self.assertEqual(result['candidates'][0]['original_candidate_ids'],['c0','c16'])
        self.assertEqual(result['candidates'][1]['status'],'reference')
        self.assertNotIn('original_candidate_ids',result['candidates'][1])

    def test_new_global_duplicate_without_bilateral_evidence_is_not_cached_and_resumes(self):
        import tempfile,json
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            merge=True
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates']=[dict(self_outer.candidate(cid,'e0000001'),sources=[self.source]) for cid in ('c1','c2')]
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    for row in result['candidates']: row.update(status='reference',reason='保留独立机制参考')
                if 'OUTPUT_CONTRACT:batched-v1-global' in prompt:
                    self_outer.assertEqual(payload['duplicate_evidence']['candidates'],[])
                    result={'adjustments':[{'id':'c2','status':'rejected','reason':'重复','canonical_id':'c1','coverage_reason':'相同机制全部覆盖'}] if self.merge else [],'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':['c1'],'reason':'保留参考'}],'gaps':[]}
                return result
        self_outer=self
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); output=Path(directory)/'out'; runner=Runner(gaps=True)
            with self.assertRaises(ValueError): ebook_pipeline.distill(path,output,runner)
            before={p.name:p.read_bytes() for p in (output/'.cache').glob('*.json')}
            self.assertEqual(len(before),5)
            self.assertEqual(len(list((output/'.diagnostics').glob('batched-v1-global*.json'))),1)
            runner.merge=False; count=len(runner.calls); updates=[]
            ebook_pipeline.distill(path,output,runner,progress=updates.append)
            self.assertEqual(len(runner.calls)-count,5)
            self.assertEqual(before,{name:(output/'.cache'/name).read_bytes() for name in before})

    def test_global_failure_estimate_excludes_revalidated_cached_batches(self):
        import tempfile,json
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            broken=True
            candidate_count=33
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates']=[dict(self_outer.candidate('c'+str(i),'e0000001'),sources=[self.source]) for i in range(self.candidate_count)]
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    for row in result['candidates']: row.update(status='reference',reason='保留参考')
                if self.broken and 'OUTPUT_CONTRACT:batched-v1-global' in prompt: result['task_audit']=[]
                return result
        self_outer=self
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); output=Path(directory)/'out'; runner=Runner(gaps=True)
            with self.assertRaises(ValueError): ebook_pipeline.distill(path,output,runner)
            runner.broken=False; updates=[]; count=len(runner.calls)
            ebook_pipeline.distill(path,output,runner,progress=updates.append)
            estimate=next(u['estimate'] for u in updates if u['stage']=='batched-v1-plan')
            self.assertEqual(estimate['remaining_model_calls'],5)
            self.assertEqual(estimate.get('cached_verification_batches'),3)
            self.assertEqual(estimate.get('maximum_additional_model_calls'),9)
            self.assertEqual(estimate.get('logical_remaining_stages'),8)
            self.assertEqual(len(runner.calls)-count,5)
            # A forged cached citation must be counted as a paid regeneration,
            # using the same complete source gate as the subsequent call.
            for file in (output/'.cache').glob('*.json'):
                saved=json.loads(file.read_text(encoding='utf-8'))
                if saved.get('candidates') and saved['candidates'][0]['id']=='c16' and saved['candidates'][0].get('status'):
                    saved['candidates'][0]['sources'][0]['quote']='伪造引文'
                    file.write_text(json.dumps(saved,ensure_ascii=False),encoding='utf-8'); break
            updates=[]; count=len(runner.calls)
            ebook_pipeline.distill(path,output,runner,progress=updates.append)
            estimate=next(u['estimate'] for u in updates if u['stage']=='batched-v1-plan')
            self.assertEqual(estimate['cached_verification_batches'],2)
            self.assertEqual(estimate['remaining_model_calls'],6)
            self.assertEqual(len(runner.calls)-count,1)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); output=Path(directory)/'out'; runner=Runner(gaps=True); runner.candidate_count=961
            with self.assertRaises(ValueError): ebook_pipeline.distill(path,output,runner,allow_large=True)
            runner.broken=False; updates=[]; count=len(runner.calls)
            # The logical total exceeds 65, but the authorized cached batch
            # sequence requires only the closing stage and downstream reserve.
            ebook_pipeline.distill(path,output,runner,progress=updates.append)
            estimate=next(u['estimate'] for u in updates if u['stage']=='batched-v1-plan')
            self.assertGreater(estimate['minimum_model_calls'],65)
            self.assertEqual(estimate['cached_verification_batches'],61)
            self.assertEqual(estimate['maximum_additional_model_calls'],9)
            self.assertEqual(len(runner.calls)-count,5)

    def candidate(self,cid='c1',element='e1'):
        return {'id':cid,'title':'相同标题','type':'framework','summary':'不同机制 '+cid,'task_ids':['t1'],'sources':[{'element_id':element,'quote':'原文','location':'chapter'}]}

    def test_batch_contract_rejects_missing_duplicate_foreign_boolean_and_changed_sources(self):
        import copy
        import ebook_verification as v
        candidate=self.candidate(); payload={'assigned_ids':['c1'],'candidates':[candidate]}
        valid={'candidates':[dict(candidate,status='needs_review',reason='跨章条件冲突')],'gaps':['条件未明']}
        self.assertEqual(v.validate_batch(valid,payload),valid)
        invalid=[{'candidates':[],'gaps':[]},dict(valid,candidates=valid['candidates']*2),dict(valid,candidates=[dict(valid['candidates'][0],id='c2')]),dict(valid,candidates=[dict(valid['candidates'][0],status='validated',verification={'V1':True,'V2':True,'V3':True})])]
        changed=copy.deepcopy(valid); changed['candidates'][0]['sources'][0]['quote']='伪造引用'; invalid.append(changed)
        for output in invalid:
            with self.subTest(output=output),self.assertRaises(ValueError): v.validate_batch(output,payload)

    def test_alignment_requires_exact_partition_and_member_representative(self):
        import ebook_verification as v
        candidates=[self.candidate('c1'),self.candidate('c2')]
        for groups in ([],[{'candidate_ids':['c1','c2'],'canonical_id':'unknown','reason':'same'}],[{'candidate_ids':['c1','c2','c1'],'canonical_id':'c1','reason':'same'}]):
            with self.subTest(groups=groups),self.assertRaises(ValueError): v.validate_alignment({'groups':groups,'gaps':[]},candidates)

    def test_batch_rejects_local_duplicate_cycle_before_cache(self):
        import ebook_verification as v
        candidates=[self.candidate('c1'),self.candidate('c2')]
        output={'candidates':[dict(c,status='rejected',reason='重复',canonical_id='c2' if c['id']=='c1' else 'c1',coverage_reason='完整覆盖') for c in candidates],'gaps':[]}
        with self.assertRaises(ValueError): v.validate_batch(output,{'assigned_ids':['c1','c2'],'candidates':candidates})

    def test_malformed_ids_raise_contract_errors(self):
        import ebook_verification as v
        candidate=self.candidate()
        with self.assertRaises(ValueError): v.validate_batch({'candidates':[dict(candidate,id=[],status='reference',reason='参考')],'gaps':[]},{'assigned_ids':['c1'],'candidates':[candidate]})

    def test_global_cannot_overwrite_candidate_sources_or_tasks(self):
        import ebook_verification as v
        candidate=self.candidate(); batch={'candidates':[dict(candidate,status='reference',reason='参考')],'gaps':[]}
        closing={'adjustments':[{'id':'c1','status':'reference','reason':'参考','sources':[]}],'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':['c1'],'reason':'参考'}],'gaps':[]}
        with self.assertRaises(ValueError): v.merge_verification([candidate],[batch],closing,{'key_tasks':[{'id':'t1'}]},[])

    def test_global_rejects_upgrade_cycles_rejected_target_and_invalid_reference(self):
        import ebook_verification as v
        candidates=[self.candidate('c1'),self.candidate('c2')]
        batch={'candidates':[dict(c,status='needs_review',reason='待查') for c in candidates],'gaps':['批次缺口']}
        overview={'key_tasks':[{'id':'t1'}]}
        closing={'adjustments':[],'task_audit':[{'task_id':'t1','status':'needs_review','candidate_ids':['c1'],'reason':'待查'}],'gaps':[]}
        invalid=[dict(closing,adjustments=[{'id':'c1','status':'validated','reason':'升级'}]),dict(closing,adjustments=[{'id':'c1','status':'rejected','reason':'重复','canonical_id':'c2','coverage_reason':'完整覆盖'},{'id':'c2','status':'rejected','reason':'重复','canonical_id':'c1','coverage_reason':'完整覆盖'}]),dict(closing,adjustments=[{'id':'c1','status':'rejected','reason':'重复','canonical_id':'unknown','coverage_reason':'完整覆盖'}]),dict(closing,task_audit=[dict(closing['task_audit'][0],status='reference')]),dict(closing,task_audit=[]),dict(closing,task_audit=closing['task_audit']*2)]
        for output in invalid:
            with self.subTest(output=output),self.assertRaises(ValueError): v.merge_verification(candidates,[batch],output,overview,[])

    def test_duplicate_merge_preserves_sources_ids_and_all_gaps(self):
        import ebook_verification as v
        candidates=[self.candidate('c1'),self.candidate('c2','e2')]
        batch={'candidates':[dict(candidates[0],status='reference',reason='参考'),dict(candidates[1],status='rejected',reason='同一机制',canonical_id='c1',coverage_reason='全部条件及出处已由 c1 覆盖')],'gaps':['批次缺口']}
        closing={'adjustments':[],'task_audit':[{'task_id':'t1','status':'reference','candidate_ids':['c1'],'reason':'代表保留参考'}],'gaps':['审计缺口']}
        result=v.merge_verification(candidates,[batch],closing,{'key_tasks':[{'id':'t1'}]},['原始缺口'])
        self.assertEqual(result['candidates'][0]['original_candidate_ids'],['c1','c2'])
        self.assertEqual(len(result['candidates'][0]['sources']),2)
        self.assertEqual(result['gaps'],['原始缺口','批次缺口','审计缺口'])

    def test_global_input_uses_light_decisions_and_only_duplicate_evidence(self):
        import tempfile,json
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                if 'OUTPUT_CONTRACT:batched-v1-global' in prompt:
                    payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
                    self_outer.assertNotIn('original_candidates',payload)
                    self_outer.assertNotIn('sources',payload['decisions'][0])
                return super().generate(prompt,*args,**kwargs)
        self_outer=self
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8')
            ebook_pipeline.distill(path,Path(directory)/'out',Runner(methods=True))

    def test_progress_final_total_counts_pressure_once(self):
        import tempfile
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        for methods in (False,True):
            with self.subTest(methods=methods),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); updates=[]; runner=ContractRunner(methods=methods)
                ebook_pipeline.distill(path,Path(directory)/'out',runner,progress=updates.append)
                self.assertEqual(updates[-1]['completed'],len(runner.calls))
                self.assertEqual(updates[-1]['total'],len(runner.calls))

    def test_single_large_evidence_requires_confirmation_then_reuses_prefix(self):
        import tempfile,json
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            extracted=False
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    if self.extracted: result['candidates']=[]
                    self.extracted=True
                return result
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文'+'字'*25000,encoding='utf-8'); output=Path(directory)/'out'; runner=Runner(methods=True)
            with self.assertRaises(ebook_pipeline.BudgetRequired) as gate: ebook_pipeline.distill(path,output,runner)
            self.assertGreater(gate.exception.estimate['evidence_characters'][0],24000)
            self.assertGreater(gate.exception.estimate['shared_context_characters'],0)
            self.assertFalse(any('OUTPUT_CONTRACT:batched-v1-batch' in p for p in runner.calls))
            before={p.name:p.read_bytes() for p in (output/'.cache').glob('*.json')}
            ebook_pipeline.distill(path,output,runner,allow_large=True)
            self.assertEqual(before,{name:(output/'.cache'/name).read_bytes() for name in before})

    def test_forged_batch_extra_quote_is_diagnostic_not_cache(self):
        import tempfile
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    result['candidates'][0]['sources'].append({'element_id':'e0000001','quote':'伪造','location':'line 1'})
                return result
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); output=Path(directory)/'out'
            with self.assertRaises(ValueError): ebook_pipeline.distill(path,output,Runner(methods=True))
            self.assertEqual(len(list((output/'.cache').glob('*.json'))),4)
            self.assertEqual(len(list((output/'.diagnostics').glob('batched-v1-batch-1*.json'))),1)

    def test_merged_candidate_sources_and_ids_survive_final_methods(self):
        import tempfile,json
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates'].append(dict(self_outer.candidate('c2','e0000001'),type='principle',sources=[dict(self.source,quote='条件')]))
                if 'OUTPUT_CONTRACT:batched-v1-alignment' in prompt:
                    result['groups']=[{'candidate_ids':['c1','c2'],'canonical_id':'c1','reason':'同机制待核验'}]
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    result['candidates'][1].update(status='rejected',canonical_id='c1',coverage_reason='全部输入、条件和跨章证据完整覆盖')
                return result
        self_outer=self
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文条件',encoding='utf-8')
            result=ebook_pipeline.distill(path,Path(directory)/'out',Runner(methods=True))
            self.assertEqual(result['methods'][0].get('original_candidate_ids'),['c1','c2'])
            self.assertIn('条件',[s['quote'] for s in result['methods'][0]['sources']])

    def test_pipeline_uses_batched_contract_and_reuses_cache(self):
        import tempfile
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                import json
                payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
                if 'OUTPUT_CONTRACT:verification' in prompt:
                    raise AssertionError('pipeline still uses monolithic verification')
                if 'OUTPUT_CONTRACT:batched-v1-alignment' in prompt:
                    self.calls.append(prompt)
                    return {'groups':[{'candidate_ids':['c1'],'canonical_id':'c1','reason':'独立机制'}],'gaps':[]}
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    self.calls.append(prompt)
                    return {'candidates':[dict(payload['candidates'][0],status='needs_review',reason='条件需核查')],'gaps':[]}
                if 'OUTPUT_CONTRACT:batched-v1-global' in prompt:
                    self.calls.append(prompt)
                    return {'adjustments':[],'task_audit':[{'task_id':'t1','status':'needs_review','candidate_ids':['c1'],'reason':'条件需核查'}],'gaps':[]}
                if 'OUTPUT_CONTRACT:ria' in prompt or 'OUTPUT_CONTRACT:organization' in prompt:
                    result=super().generate(prompt,*args,**kwargs); result['cards']=[]; return result
                if 'OUTPUT_CONTRACT:analysis\n' in prompt:
                    result=super().generate(prompt,*args,**kwargs); result['methods']=[]; return result
                return super().generate(prompt,*args,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文检查输入',encoding='utf-8'); runner=Runner(methods=True)
            output=Path(directory)/'out'; ebook_pipeline.distill(path,output,runner)
            self.assertTrue(any('OUTPUT_CONTRACT:batched-v1-batch' in p for p in runner.calls),'pipeline still uses monolithic verification')
            before={p.name:p.read_bytes() for p in (output/'.cache').glob('*.json')}
            count=len(runner.calls); ebook_pipeline.distill(path,output,runner)
            self.assertEqual(count,len(runner.calls)); self.assertEqual(before,{p.name:p.read_bytes() for p in (output/'.cache').glob('*.json')})

    def test_stable_batches_keep_last_candidate(self):
        import ebook_pipeline
        self.assertTrue(hasattr(ebook_pipeline,'verification_batches'),'batched verification production API missing')
        candidates=[{'id':str(i),'sources':[{'element_id':'e'}]} for i in range(33)]
        alignment={'groups':[{'candidate_ids':[c['id']], 'canonical_id':c['id'],'reason':'independent'} for c in candidates]}
        batches=ebook_pipeline.verification_batches(candidates,alignment,{'elements':[{'element_id':'e','text':'e'}]},[])
        self.assertEqual([len(b['assigned_ids']) for b in batches],[16,16,1])
        self.assertEqual([x for b in batches for x in b['assigned_ids']],[str(i) for i in range(33)])
        self.assertEqual([len(b['assigned_ids']) for b in ebook_pipeline.verification_batches(candidates[:17],alignment,{'elements':[{'element_id':'e','text':'e'}]},[])],[16,1])
        self.assertEqual(ebook_pipeline.verification_batches([],{'groups':[]},{'elements':[]},[]),[])

    def test_large_evidence_shrinks_batches_without_truncation(self):
        import ebook_verification as v
        candidates=[self.candidate('c'+str(i),'e'+str(i)) for i in range(17)]
        elements=[{'element_id':'e'+str(i),'text':'原文'+'字'*2000,'location':'chapter'} for i in range(17)]
        alignment={'groups':[{'candidate_ids':[c['id']],'canonical_id':c['id'],'reason':'独立机制'} for c in candidates]}
        batches=v.verification_batches(candidates,alignment,{'elements':elements},[])
        self.assertLess(len(batches[0]['assigned_ids']),16)
        self.assertEqual([cid for b in batches for cid in b['assigned_ids']],[c['id'] for c in candidates])
        self.assertTrue(all(len(e['text'])==2002 for b in batches for e in b['evidence_elements']))
        huge=v.verification_batches([candidates[0]],{'groups':[alignment['groups'][0]]},{'elements':[dict(elements[0],text='字'*25000)]},[])
        self.assertTrue(huge[0]['requires_budget_confirmation'])
        self.assertEqual(len(huge[0]['evidence_elements'][0]['text']),25000)

    def test_failed_batch_global_and_cancel_resume_only_current_stage(self):
        import tempfile,json,threading
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        class Runner(ContractRunner):
            def __init__(self,broken,event=None): super().__init__(); self.broken=broken; self.event=event
            def generate(self,prompt,*args,**kwargs):
                payload=json.loads(prompt.split('SOURCE_DATA_JSON:\n',1)[1])
                if self.broken and 'OUTPUT_CONTRACT:'+self.broken in prompt:
                    if self.broken=='batched-v1-batch' and payload['assigned_ids'][0]!='c16': pass
                    else:
                        if self.event:
                            result=super().generate(prompt,*args,**kwargs)
                            for row in result['candidates']: row.update(status='reference',reason='保留来源参考')
                            self.event.set()
                            return result
                        self.calls.append(prompt)
                        return {'candidates':[],'gaps':[]} if self.broken=='batched-v1-batch' else {'adjustments':[],'task_audit':[{'task_id':'fake'}],'gaps':[]}
                result=super().generate(prompt,*args,**kwargs)
                if 'OUTPUT_CONTRACT:joint-extraction' in prompt:
                    result['candidates']=[{'id':'c'+str(i),'title':'机制 '+str(i),'type':'framework','summary':'独立机制 '+str(i),'task_ids':[],'sources':[self.source]} for i in range(33)]
                if 'OUTPUT_CONTRACT:batched-v1-batch' in prompt:
                    for row in result['candidates']: row.update(status='reference',reason='保留来源参考')
                return result
        for broken,cancel in [('batched-v1-batch',False),('batched-v1-global',False),('batched-v1-batch',True)]:
            with self.subTest(broken=broken,cancel=cancel),tempfile.TemporaryDirectory() as directory:
                path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); output=Path(directory)/'out'; event=threading.Event() if cancel else None; runner=Runner(broken,event)
                with self.assertRaises(InterruptedError if cancel else ValueError): ebook_pipeline.distill(path,output,runner,cancel_event=event)
                before={p.name:p.read_bytes() for p in (output/'.cache').glob('*.json')}
                self.assertEqual(len(before),5 if broken=='batched-v1-batch' else 7)
                runner.broken=None
                if event: event.clear()
                count=len(runner.calls); ebook_pipeline.distill(path,output,runner,cancel_event=event)
                self.assertEqual(len(runner.calls)-count,7 if broken=='batched-v1-batch' else 5)
                self.assertEqual(before,{name:(output/'.cache'/name).read_bytes() for name in before})

    def test_context_understanding_invalidates_only_changed_stage0_cache(self):
        import tempfile,subprocess
        import ebook_pipeline
        from test_ebook_core import ContractRunner
        namespace={'__file__':ebook_pipeline.__file__,'__name__':'base_pipeline'}
        source=subprocess.check_output(['git','show','a9c06c6:reading-yearbook-skill/scripts/ebook_pipeline.py']).decode('utf-8')
        exec(compile(source,'base_pipeline','exec'),namespace)
        class Stop(ContractRunner):
            def generate(self,prompt,*args,**kwargs):
                if 'OUTPUT_CONTRACT:verification' in prompt or 'OUTPUT_CONTRACT:batched-v1-alignment' in prompt: raise RuntimeError('stop before verification')
                return super().generate(prompt,*args,**kwargs)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.txt'; path.write_text('原文',encoding='utf-8'); first=Stop(methods=True); second=Stop(methods=True)
            for engine,out,runner in [(namespace['distill'],'old',first),(ebook_pipeline.distill,'new',second)]:
                with self.assertRaises(RuntimeError): engine(path,Path(directory)/out,runner)
            self.assertEqual(len(first.calls),7); self.assertEqual(len(second.calls),3)
            # Understanding now retains characters and argument progression. These
            # two stages must not reuse an older, narrower understanding prompt.
            for old,new in zip(first.calls[:2],second.calls[:2]): self.assertNotEqual(old,new)
            self.assertIn('OUTPUT_CONTRACT:joint-extraction',second.calls[2])
            caches=lambda out:{p.name:p.read_bytes() for p in (Path(directory)/out/'.cache').glob('*.json')}
            old,new=caches('old'),caches('new')
            common=old.keys() & new.keys()
            self.assertEqual(len(common),0)
            for key in common: self.assertEqual(old[key],new[key])

if __name__=='__main__': unittest.main()
