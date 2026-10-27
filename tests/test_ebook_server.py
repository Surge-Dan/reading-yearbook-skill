import importlib.util
import json
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'
sys.path.insert(0, str(SCRIPTS))
AVAILABLE = importlib.util.find_spec('serve_ebook') is not None
if AVAILABLE:
    from serve_ebook import JobStore, create_server, offline_page


class EntryTests(unittest.TestCase):
    def test_workbench_service_exists(self):
        self.assertTrue(AVAILABLE, '缺少网页电子书服务')


class Runner:
    def info(self):
        return {'name': 'test', 'available': True}


@unittest.skipUnless(AVAILABLE, 'service not implemented')
class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.started = threading.Event()
        self.release = threading.Event()
        self.calls = []

        def pipeline(path, output_dir, runner, progress=None, cancel_event=None,
                     focus='', allow_large=False):
            self.calls.append((path.read_bytes(), focus, allow_large))
            progress({'stage': 'extract', 'message': '已读取一章', 'completed': 1, 'total': 2,'estimate':{'verification_batches':2,'shared_context_characters':300}})
            self.started.set()
            while not self.release.wait(.01):
                if cancel_event.is_set():
                    raise InterruptedError('已取消')
            output_dir.mkdir(parents=True, exist_ok=True)
            (output_dir / 'DIGEST.md').write_text('书本精华', 'utf-8')
            return {'schema_version': 1, 'book': {'title': '测试书', 'author': ''},
                    'overview': '精华', 'themes': [], 'methods': [], 'cases': [],
                    'counterexamples': [], 'glossary': [], 'limitations': [],
                    'coverage': {'complete': True}, 'quality_status': 'needs_review'}

        self.store = JobStore(Path(self.tmp.name), Runner(), pipeline=pipeline)
        self.server = create_server(self.store, port=0)
        self.origin = f'http://127.0.0.1:{self.server.server_port}'
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.release.set()
        self.server.shutdown()
        self.server.server_close()
        self.store.close()
        self.tmp.cleanup()

    def request(self, path, body=None, token=True, origin=None, **headers):
        if token:
            headers['X-Ebook-Token'] = self.store.token
        if body is not None:
            headers['Origin'] = origin or self.origin
        req = urllib.request.Request(self.origin + path, data=body, headers=headers)
        with urllib.request.urlopen(req, timeout=3) as r:
            return r.status, r.headers, r.read()

    def wait_state(self, job_id, state):
        for _ in range(200):
            job = self.store.get(job_id)
            if job['state'] == state:
                return job
            time.sleep(.01)
        self.fail(f'job did not reach {state}: {job}')

    def test_upload_progress_result_and_restore(self):
        status, _, data = self.request('/api/jobs?name=book.txt&focus=work', b'chapter')
        self.assertEqual(status, 202)
        job_id = json.loads(data)['job']['id']
        self.assertTrue(self.started.wait(2))
        job = self.store.get(job_id)
        self.assertEqual(job['completed'], 1)
        self.assertEqual(job['stage'], 'extract')
        self.assertEqual(job.get('estimate',{}).get('verification_batches'),2)
        self.release.set()
        done = self.wait_state(job_id, 'completed')
        self.assertEqual(done['digest'], '书本精华')
        self.assertEqual(self.calls, [(b'chapter', 'work', False)])
        # Restart after the completed worker has persisted its final state.
        self.store.executor.submit(lambda: None).result(timeout=3)
        restored = JobStore(Path(self.tmp.name), Runner(), pipeline=lambda *a, **k: {})
        try:
            self.assertEqual(restored.get(job_id)['analysis']['book']['title'], '测试书')
        finally:
            restored.close()
        _, headers, page = self.request(done['result_url'], token=False)
        self.assertIn('EBOOK_RESULT', page.decode('utf-8'))
        self.assertNotIn(self.store.token, page.decode('utf-8'))
        self.assertEqual(headers['Content-Type'].split(';')[0], 'text/html')

    def test_cross_origin_missing_token_and_bad_host_rejected(self):
        for path, body, opts in [('/api/state', None, {'token': False}),
                                 ('/api/jobs?name=a.txt', b'a', {'origin': 'https://evil.example'}),
                                 ('/', None, {'Host': 'evil.example'})]:
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(path, body, **opts)
            self.assertEqual(error.exception.code, 403)

    def test_original_upload_stem_is_used_for_filename_title_fallback(self):
        from test_ebook_core import ContractRunner
        self.store.pipeline=None
        self.store.runner=ContractRunner()
        for name,title in [('folder/原书标题.txt','原书标题'),('folder/原书标题.md','原书标题'),('C:\\fakepath\\原:书?标题.txt','原-书-标题')]:
            with self.subTest(name=name):
                job=self.store.create(name,'原文'.encode('utf-8'))
                done=self.wait_state(job['id'],'completed')
                self.assertEqual(done['analysis']['book']['title'],title)
                self.assertIn('# '+title,done['digest'])
                self.assertTrue((self.store.jobs_dir/job['id']/('source'+Path(name).suffix)).is_file())

    def test_cancel_single_task_and_retry(self):
        _, _, data = self.request('/api/jobs?name=a.txt', b'body')
        job_id = json.loads(data)['job']['id']
        self.assertTrue(self.started.wait(2))
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/jobs?name=b.txt', b'body')
        self.assertEqual(err.exception.code, 409)
        self.request(f'/api/jobs/{job_id}/cancel', b'')
        self.wait_state(job_id, 'cancelled')
        self.release.set()
        self.request(f'/api/jobs/{job_id}/retry', b'')
        self.wait_state(job_id, 'completed')
        self.assertEqual(len(self.calls), 2)

    def test_bad_file_and_traversal_not_written(self):
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/jobs?name=bad.exe', b'x')
        self.assertEqual(err.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/jobs?name=empty.txt', b'')
        self.assertEqual(err.exception.code, 400)
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/results/../../test.html', token=False)
        self.assertIn(err.exception.code, (400, 404))

    def test_cancelling_queued_job_does_not_leave_busy_state(self):
        self.store.executor.submit(self.release.wait)
        job = self.store.create('queued.txt', b'body')
        self.store.action(job['id'], 'cancel')
        self.assertEqual(self.store.get(job['id'])['state'], 'cancelled')

    def test_budget_confirmation_is_required_before_retrying_large_book(self):
        class BudgetError(ValueError):
            estimate = {'chunks': 40, 'calls': 48}
        def over_budget(*args, allow_large=False, **kwargs):
            if not allow_large:
                raise BudgetError('较长书籍需要确认')
            deep = args[1]
            deep.mkdir(parents=True, exist_ok=True)
            (deep / 'DIGEST.md').write_text('large digest', 'utf-8')
            return {'book': {'title': 'large'}}
        self.store.pipeline = over_budget
        job = self.store.create('large.txt', b'body')
        self.wait_state(job['id'], 'needs_approval')
        self.assertEqual(self.store.get(job['id'])['estimate']['calls'], 48)
        self.store.action(job['id'], 'approve')
        self.wait_state(job['id'], 'completed')

    def test_offline_result_escapes_model_script(self):
        page = offline_page({'book': {'title': '</script><script>alert(1)</script>'}}, 'text')
        self.assertNotIn('</script><script>alert(1)', page)
        self.assertNotIn('X-Ebook-Token', page.split('window.EBOOK_RESULT=')[0])

    def test_filesystem_error_does_not_expose_private_path(self):
        secret_path = str(Path(self.tmp.name) / 'private-book' / 'DIGEST.md')
        def broken(*args, **kwargs):
            raise FileNotFoundError(2, 'missing', secret_path)
        self.store.pipeline = broken
        job = self.store.create('error.txt', b'body')
        failed = self.wait_state(job['id'], 'failed')
        self.assertNotIn(secret_path, failed['error'])
        self.assertIn('本地', failed['error'])

    def test_invalid_saved_job_is_ignored_on_restart(self):
        job_dir = self.store.jobs_dir / ('a' * 32)
        job_dir.mkdir()
        (job_dir / 'state.json').write_text(json.dumps({'id': 'a' * 32, 'state': 'failed'}), 'utf-8')
        restored = JobStore(Path(self.tmp.name), Runner())
        try:
            self.assertEqual(restored.state()['jobs'], [])
        finally:
            restored.close()

    def test_non_ascii_token_returns_forbidden(self):
        with self.assertRaises(urllib.error.HTTPError) as err:
            self.request('/api/state', token=False, **{'X-Ebook-Token': 'é'})
        self.assertEqual(err.exception.code, 403)


if __name__ == '__main__':
    unittest.main()
