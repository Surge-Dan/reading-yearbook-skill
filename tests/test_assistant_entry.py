import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
import urllib.error
from unittest.mock import patch
from pathlib import Path

SCRIPTS=Path(__file__).resolve().parents[1]/'reading-yearbook-skill/scripts'
sys.path.insert(0,str(SCRIPTS))
from ebook_agent import Client,local_source
from ebook_agent_bridge import AgentRunner
from serve_ebook import JobStore,create_server


class AssistantEntryTests(unittest.TestCase):
    def wait_prepared(self,job):
        import time
        for _ in range(200):
            current=self.store.get(job['id'])
            if current['state']!='queued':return current
            time.sleep(.01)
        self.fail('Source preparation did not finish')

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.store=JobStore(self.root,AgentRunner())
        self.server=create_server(self.store)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.client=Client(self.root)

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.store.close();self.tmp.cleanup()

    def test_private_create_path_cancel_retry_and_approval_without_web(self):
        source=self.root/'book.txt';source.write_text('受控短篇正文。',encoding='utf-8')
        job=self.client.call('create-file',{'path':str(source),'session':'chat'})['job']
        job=self.wait_prepared(job)
        self.assertEqual(job['state'],'awaiting_agent')
        self.assertEqual((self.store.jobs_dir/job['id']/'source.txt').read_bytes(),source.read_bytes())
        with self.assertRaises(ValueError):self.client.call('cancel',{'session':'other'},job['id'])
        self.client.call('cancel',{'session':'chat'},job['id'])
        retried=self.client.call('retry',{'session':'chat'},job['id'])['job']
        self.assertEqual(self.wait_prepared(retried)['state'],'awaiting_agent')
        self.store.jobs[job['id']]['state']='needs_approval'
        self.assertTrue(self.client.call('approve',{'session':'chat'},job['id'])['job']['allow_large'])

    def test_cli_creates_title_and_current_session_owns_claim(self):
        result=subprocess.run([sys.executable,'-X','utf8',str(SCRIPTS/'ebook_agent.py'),'--output',str(self.root),
            'create-title','--title','同名书','--author','作者','--session','chat'],capture_output=True,text=True,encoding='utf-8')
        self.assertEqual(result.returncode,0,result.stderr)
        job=json.loads(result.stdout)['job']
        self.assertEqual(job['book_query'],{'title':'同名书','author':'作者'})
        with self.assertRaises(ValueError):self.client.call('claim',{'session':'other','host':'test','model':'fixture'},job['id'])
        self.client.call('cancel',{'session':'chat'},job['id'])

    def test_reader_token_cannot_read_path_and_links_rejected(self):
        origin=self.client.origin
        request=urllib.request.Request(origin+'/api/agent/create-file',data=json.dumps({'path':str(self.root/'secret.txt'),'session':'chat'}).encode(),
            headers={'Origin':origin,'X-Ebook-Token':self.store.token})
        with self.assertRaises(urllib.error.HTTPError) as caught:urllib.request.urlopen(request)
        self.assertEqual(caught.exception.code,403)
        for name,content in [('empty.txt',''),('bad.exe','content')]:
            path=self.root/name;path.write_text(content,encoding='utf-8')
            with self.assertRaises(ValueError):self.client.call('create-file',{'path':str(path),'session':'chat'})
        source=self.root/'book.txt';source.write_text('正文',encoding='utf-8');link=self.root/'link.txt'
        try:link.symlink_to(source)
        except OSError:return
        with self.assertRaises(ValueError):self.client.call('create-file',{'path':str(link),'session':'chat'})

    def test_network_and_device_paths_rejected_before_filesystem_access(self):
        for path in ('\\\\server\\share\\book.txt','\\\\?\\C:\\book.txt'):
            with self.subTest(path=path),patch('ebook_agent.Path.lstat',side_effect=AssertionError('must not touch remote/device path')):
                with self.assertRaises(ValueError):local_source(path)

    def test_private_selection_uses_session_and_selection_identity(self):
        job=self.client.call('create-title',{'title':'同名书','session':'chat'})['job']
        # Controlled pending choice: selection still goes through real store validation.
        self.store.jobs[job['id']].update(state='needs_book_confirmation',selection_id='selection',book_candidates=[{'id':'b1'}])
        self.store.runners[job['id']]=object()
        with self.assertRaises(ValueError):self.client.call('select-book',{'session':'chat','book_id':'b1','selection_id':'stale'},job['id'])
        selected=self.client.call('select-book',{'session':'chat','book_id':'b1','selection_id':'selection'},job['id'])['job']
        self.assertEqual(selected['selected_book'],'b1')

    def test_failure_after_pipeline_publication_archives_bundle(self):
        from test_assistant_distillation import JointRunner
        import ebook_pipeline
        def controlled(path,output,runner,**kwargs):
            return ebook_pipeline.distill(path,output,JointRunner(),cancel_event=kwargs['cancel_event'])
        self.store.pipeline=controlled
        job=self.client.call('create-title',{'title':'临时','session':'chat'})['job']
        self.client.call('cancel',{'session':'chat'},job['id'])
        source=self.root/'book.txt';source.write_text('受控短篇正文。',encoding='utf-8')
        job=self.client.call('create-file',{'path':str(source),'session':'chat'})['job']
        job=self.wait_prepared(job)
        import time
        with patch('serve_ebook.offline_page',side_effect=ValueError('render failed')):
            self.client.call('claim',{'session':'chat','host':'test','model':'fixture'},job['id'])
            for _ in range(200):
                if self.store.get(job['id'])['state']=='failed':break
                time.sleep(.01)
        self.assertEqual(self.store.get(job['id'])['state'],'failed')
        deep=self.store.jobs_dir/job['id']/'deep'
        self.assertFalse((deep/'distillation.json').exists())
        self.assertTrue(list((deep/'.history').glob('*/distillation.json')))

    def test_slow_parser_does_not_delay_creation_or_orphan_job(self):
        import ebook_document
        source=self.root/'book.txt';source.write_text('受控短篇正文。',encoding='utf-8')
        entered,release,returned=threading.Event(),threading.Event(),threading.Event()
        results=[];original=ebook_document.parse_document
        def slow(path):
            entered.set();release.wait(3)
            return original(path)
        def create():
            try:results.append(self.client.call('create-file',{'path':str(source),'session':'chat'}))
            finally:returned.set()
        with patch('ebook_document.parse_document',side_effect=slow):
            worker=threading.Thread(target=create);worker.start()
            try:
                self.assertTrue(entered.wait(1))
                self.assertTrue(returned.wait(.5),'Private create must return identity before parsing finishes')
                self.assertEqual(len(self.store.jobs),1)
            finally:release.set();worker.join(3)
        self.assertEqual(self.wait_prepared(results[0]['job'])['state'],'awaiting_agent')

    def test_prepared_source_write_failure_finishes_job_and_allows_next_book(self):
        import serve_ebook
        source=self.root/'book.txt';source.write_text('受控短篇正文。',encoding='utf-8')
        original=serve_ebook.atomic_json
        def disk_failure(path,value):
            if Path(path).name=='parsed-source.json':
                raise OSError('private book text at C:/private/book.txt')
            return original(path,value)
        with patch('serve_ebook.atomic_json',side_effect=disk_failure):
            job=self.client.call('create-file',{'path':str(source),'session':'chat'})['job']
            # Drain the single preparation executor without relying on parser timing.
            self.store.executor.submit(lambda:None).result(timeout=3)
        current=self.store.get(job['id'])
        self.assertEqual(current['state'],'failed')
        self.assertEqual(current['error'],serve_ebook.public_error(OSError()))
        self.assertNotIn('private',json.dumps(current))
        saved=json.loads((self.store.jobs_dir/job['id']/'state.json').read_text('utf-8'))
        self.assertEqual(saved['state'],'failed')
        next_job=self.client.call('create-title',{'title':'下一本','session':'chat'})['job']
        self.assertEqual(next_job['state'],'awaiting_agent')

    def test_late_preparation_cannot_revive_cancelled_or_retried_attempt(self):
        import ebook_document
        import serve_ebook
        source=self.root/'book.txt';source.write_text('受控短篇正文。',encoding='utf-8')
        original_parse=ebook_document.parse_document;original_write=serve_ebook.atomic_json
        for retry in (False,True):
            entered,release=threading.Event(),threading.Event();writes=[];calls=[]
            def slow(path):
                calls.append(path)
                if len(calls)==1:entered.set();release.wait(3)
                return original_parse(path)
            def record(path,value):
                if Path(path).name=='parsed-source.json':writes.append(path)
                return original_write(path,value)
            with self.subTest(retry=retry),patch('ebook_document.parse_document',side_effect=slow),patch('serve_ebook.atomic_json',side_effect=record):
                job=self.client.call('create-file',{'path':str(source),'session':'chat'})['job']
                try:
                    self.assertTrue(entered.wait(1))
                    old_event=self.store.events[job['id']]
                    self.client.call('cancel',{'session':'chat'},job['id'])
                    if retry:
                        self.client.call('retry',{'session':'chat'},job['id'])
                        self.assertIsNot(self.store.events[job['id']],old_event)
                        # A superseded identity must be rejected even without its
                        # cancellation bit; the fresh attempt owns the result.
                        old_event.clear()
                finally:release.set()
                self.store.executor.submit(lambda:None).result(timeout=3)
                current=self.store.get(job['id'])
                self.assertEqual(current['state'],'awaiting_agent' if retry else 'cancelled')
                self.assertEqual(len(writes),1 if retry else 0)
                if retry:self.client.call('cancel',{'session':'chat'},job['id'])


if __name__=='__main__':unittest.main()
