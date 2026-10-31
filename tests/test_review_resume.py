"""A completed assistant result with an unavailable review can resume safely."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))
from ebook_agent_bridge import AgentRunner
from serve_ebook import JobStore


class ReviewResumeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = JobStore(self.tmp.name, AgentRunner())
        job = self.store.create('fixture.txt', '受控正文。'.encode('utf-8'), assistant_session='owner')
        self.job_id = job['id']
        self.drain()
        self.job = self.store.jobs[self.job_id]
        self.job.update(state='completed', analysis={'review': {'status': 'unavailable',
            'reason': 'source rejected', 'paragraphs': []}}, digest='existing digest', allow_large=True)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def drain(self):
        self.store.executor.submit(lambda: None).result(timeout=3)

    def test_owner_can_retry_missing_review_preserving_source_and_stage_cache(self):
        root = self.store.jobs_dir / self.job_id
        source = (root / 'parsed-source.json').read_bytes()
        cache = root / 'deep/.cache/accepted.json'
        cache.parent.mkdir(parents=True)
        cache.write_text('{"accepted":true}', encoding='utf-8')
        self.store.agent_action(self.job_id, 'retry', {'session': 'owner'})
        self.drain()
        result = self.store.get(self.job_id)
        self.assertEqual(result['state'], 'awaiting_agent')
        self.assertTrue(result['allow_large'])
        self.assertEqual((root / 'parsed-source.json').read_bytes(), source)
        self.assertEqual(cache.read_text('utf-8'), '{"accepted":true}')
        self.assertEqual(result['analysis']['review']['status'], 'unavailable')

    def test_other_session_cannot_retry_missing_review(self):
        with self.assertRaisesRegex(ValueError, '另一个对话'):
            self.store.agent_action(self.job_id, 'retry', {'session': 'other'})
        self.assertEqual(self.job['state'], 'completed')

    def test_ready_or_absent_review_does_not_open_completed_retry(self):
        for review in ({'status': 'ready', 'paragraphs': [{'text': 'ready'}]}, None, {}):
            with self.subTest(review=review):
                self.job['analysis'] = {} if review is None else {'review': review}
                with self.assertRaisesRegex(ValueError, '不支持'):
                    self.store.agent_action(self.job_id, 'retry', {'session': 'owner'})
                self.assertEqual(self.job['state'], 'completed')

    def test_completed_review_retry_never_approves_new_cost(self):
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.store.agent_action(self.job_id, 'approve', {'session': 'owner'})
        self.assertEqual(self.job['state'], 'completed')

    def test_reader_action_cannot_resume_completed_review(self):
        with self.assertRaisesRegex(ValueError, '不支持'):
            self.store.action(self.job_id, 'retry')
        self.assertEqual(self.job['state'], 'completed')


if __name__ == '__main__':
    unittest.main()
