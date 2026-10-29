"""Explicit recovery uses fixture workers and temporary loopback only."""
import json
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'
sys.path.insert(0, str(SCRIPTS))
from ebook_agent import Client
from ebook_agent_bridge import AgentRunner
from serve_ebook import JobStore, create_server


class SessionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.calls = []
        def pipeline(path, output, runner, **kwargs):
            self.calls.append(runner.identity.copy())
            runner.prepare('fixture', {'source_hash': 'fixed-source'}, 'fixed-cache')
            runner.generate('inert fixture', cancel_event=kwargs['cancel_event'])
        self.pipeline = pipeline
        self.store = JobStore(self.root, AgentRunner(), pipeline=pipeline)

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def create(self):
        job = self.store.create('fixture.txt', b'Inert short fixture.', assistant_session='old-chat')
        self.drain()
        return job['id']

    def drain(self):
        self.store.executor.submit(lambda: None).result(timeout=3)

    def recover(self, job, **changes):
        data = dict(session='new-chat', expected_session='old-chat', confirm_transfer=True)
        data.update(changes)
        return self.store.agent_action(job, 'recover', data)

    def pending(self, job, session):
        for _ in range(200):
            result = self.store.agent_action(job, 'next', {'session': session})
            if result['request']:
                return result['request']
            time.sleep(.005)
        self.fail('fixture request was not prepared')

    def test_persisted_interrupted_task_new_session_recovers_then_retries_and_claims(self):
        job = self.create()
        identity = dict(session='old-chat', host='fixture-host', model='fixture-model')
        self.store.agent_action(job, 'claim', identity)
        old_request = self.pending(job, 'old-chat')
        old_runner = self.store.runners[job]
        self.store.agent_action(job, 'release', {'session': 'old-chat'})
        self.drain()
        self.assertEqual(self.store.get(job)['state'], 'interrupted')
        self.store.close()
        self.store = JobStore(self.root, AgentRunner(), pipeline=self.pipeline)
        source = self.store.jobs_dir / job / 'parsed-source.json'
        before = source.read_bytes()
        result = self.recover(job)['job']
        self.assertNotIn('session_transfers', result, 'private audit must not extend reader job data')
        self.assertEqual(result['state'], 'interrupted')
        self.assertEqual(result['assistant_session'], 'new-chat')
        ownership = json.loads((self.store.jobs_dir / job / '.agent/ownership.json').read_text('utf-8'))
        transfer = ownership['session_transfers'][-1]
        self.assertEqual(transfer['previous_session'], 'old-chat')
        self.assertEqual(transfer['execution_identity'], identity)
        self.assertEqual(transfer['attempt_id'], old_request['attempt_id'])
        self.assertEqual(len(self.calls), 1, 'recovery must not execute the pipeline')
        self.assertEqual(source.read_bytes(), before)
        self.assertFalse(result['allow_large'])
        saved = json.loads((self.store.jobs_dir / job / 'state.json').read_text('utf-8'))
        self.assertEqual(saved['assistant_session'], 'new-chat')
        for action in ('retry', 'approve', 'claim', 'next', 'submit', 'release'):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.store.agent_action(job, action, dict(identity, request_id=old_request['request_id'], answer={}))
        with self.assertRaises(InterruptedError):
            old_runner.submit('old-chat', old_request['request_id'], {})
        self.store.agent_action(job, 'retry', {'session': 'new-chat'})
        self.drain()
        self.store.agent_action(job, 'claim', dict(identity, session='new-chat'))
        new_request = self.pending(job, 'new-chat')
        self.assertNotEqual(new_request['attempt_id'], old_request['attempt_id'])
        with self.assertRaises(ValueError):
            self.store.agent_action(job, 'submit', {'session': 'new-chat', 'request_id': old_request['request_id'], 'answer': {}})

    def test_confirmation_expected_owner_and_new_identity_are_required(self):
        job = self.create()
        self.store.agent_action(job, 'cancel', {'session': 'old-chat'})
        self.drain()
        for changes in ({'confirm_transfer': False}, {'confirm_transfer': 'yes'},
                        {'expected_session': None}, {'expected_session': 'stale'},
                        {'session': None}, {'session': ' '}, {'session': 'old-chat'}, {'session': 'x' * 201}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.recover(job, **changes)
            self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')
        self.recover(job)
        with self.assertRaises(ValueError):
            self.recover(job, session='third-chat')

    def test_active_pending_approval_and_completed_states_cannot_transfer(self):
        job = self.create()
        for state in ('queued', 'running', 'awaiting_agent', 'awaiting_response',
                      'needs_book_confirmation', 'needs_approval', 'completed'):
            with self.subTest(state=state):
                self.store.jobs[job]['state'] = state
                with self.assertRaises(ValueError):
                    self.recover(job)
                self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')

    def test_valid_lease_blocks_transfer_even_if_state_looks_stopped(self):
        job = self.create()
        event = self.store.events[job]
        runner = AgentRunner().bind(self.store.jobs_dir / job, job,
            dict(session='old-chat', host='test', model='unknown'), cancel_event=event)
        self.store.runners[job] = runner
        self.store.jobs[job]['state'] = 'interrupted'
        with self.assertRaises(ValueError):
            self.recover(job)
        self.assertFalse(event.is_set())
        self.assertIsNone(runner.revoked)
        runner.deadline = runner.clock() - 1
        self.recover(job)
        self.assertTrue(event.is_set())
        self.assertIsNotNone(runner.revoked)
        self.assertNotIn(job, self.store.runners)
        self.assertNotIn(job, self.store.events)
        with self.assertRaises(InterruptedError):
            runner.next('old-chat')

    def test_cancelled_worker_must_finish_before_transfer(self):
        job = self.create()
        entered, resume = threading.Event(), threading.Event()
        def paused(*args, **kwargs):
            entered.set()
            resume.wait(3)
            raise InterruptedError('fixture stopped')
        self.store.pipeline = paused
        self.store.agent_action(job, 'claim', dict(session='old-chat', host='test', model='unknown'))
        self.assertTrue(entered.wait(1))
        try:
            self.store.agent_action(job, 'cancel', {'session': 'old-chat'})
            # A stopped dictionary plus cancelled event does not prove worker exit.
            self.store.jobs[job]['state'] = 'cancelled'
            with self.assertRaises(ValueError):
                self.recover(job)
        finally:
            resume.set()
            self.drain()
        self.assertEqual(self.recover(job)['job']['assistant_session'], 'new-chat')

    def test_stopped_states_and_same_owner_retry_preserve_cost_approval(self):
        job = self.create()
        self.store.agent_action(job, 'cancel', {'session': 'old-chat'})
        self.store.agent_action(job, 'retry', {'session': 'old-chat'})
        self.drain()
        self.assertEqual(self.store.get(job)['state'], 'awaiting_agent')
        for state in ('failed', 'cancelled', 'interrupted'):
            self.store.jobs[job].update(state=state, assistant_session='old-chat', allow_large=False)
            self.assertFalse(self.recover(job)['job']['allow_large'])
        self.store.agent_action(job, 'retry', {'session': 'new-chat'})
        self.drain()
        self.assertFalse(self.store.get(job)['allow_large'])

    def test_private_api_and_cli_recovery_security(self):
        job = self.create()
        self.store.agent_action(job, 'cancel', {'session': 'old-chat'})
        self.drain()
        server = create_server(self.store)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        origin = f'http://127.0.0.1:{server.server_port}'
        payload = json.dumps(dict(session='new-chat', expected_session='old-chat', confirm_transfer=True)).encode()
        try:
            cases = [dict(Origin=origin, **{'X-Ebook-Token': self.store.token}),
                     dict(Origin='https://other.invalid', **{'X-Ebook-Agent-Token': self.store.agent_token}),
                     dict(Origin=origin, Host='other.invalid', **{'X-Ebook-Agent-Token': self.store.agent_token})]
            for headers in cases:
                request = urllib.request.Request(origin + f'/api/agent/{job}/recover', data=payload, headers=headers)
                with self.assertRaises(urllib.error.HTTPError) as caught:
                    urllib.request.urlopen(request, timeout=3)
                self.assertEqual(caught.exception.code, 403)
                self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')
            base = [sys.executable, '-X', 'utf8', str(SCRIPTS / 'ebook_agent.py'), '--output', str(self.root),
                    'recover', '--job', job, '--session', 'new-chat', '--expected-session', 'old-chat']
            denied = subprocess.run(base, capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')
            result = subprocess.run(base + ['--confirm-transfer'], capture_output=True, text=True, encoding='utf-8', timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)['job']['assistant_session'], 'new-chat')
            self.assertEqual(Client(self.root).call('list')['jobs'][0]['state'], 'cancelled')
            reader = urllib.request.Request(origin + '/api/state', headers={'X-Ebook-Token': self.store.token})
            with urllib.request.urlopen(reader, timeout=3) as response:
                reader_state = json.loads(response.read())
            self.assertNotIn('session_transfers', reader_state['jobs'][0])
            self.assertNotIn('execution_identity', reader_state['jobs'][0])
            self.assertEqual(self.calls, [])
        finally:
            server.shutdown()
            server.server_close()

    def test_failed_recovery_persistence_keeps_previous_owner_and_audit(self):
        import serve_ebook
        job = self.create()
        self.store.agent_action(job, 'cancel', {'session': 'old-chat'})
        self.drain()
        original = serve_ebook.atomic_json
        for failed_name in ('ownership.json', 'state.json'):
            def fail(path, data):
                if Path(path).name == failed_name:
                    raise OSError('fixture disk failure')
                return original(path, data)
            with self.subTest(failed_name=failed_name), patch('serve_ebook.atomic_json', side_effect=fail):
                with self.assertRaises(OSError):
                    self.recover(job)
            self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')
            saved = json.loads((self.store.jobs_dir / job / 'state.json').read_text('utf-8'))
            self.assertEqual(saved['assistant_session'], 'old-chat')
            audit = self.store.jobs_dir / job / '.agent/ownership.json'
            if audit.exists():
                self.assertEqual(json.loads(audit.read_text('utf-8')).get('session_transfers', []), [])
        self.assertEqual(self.recover(job)['job']['assistant_session'], 'new-chat')

    def test_failed_claim_persistence_does_not_leave_live_runner_or_work(self):
        import serve_ebook
        job = self.create()
        original = serve_ebook.atomic_json
        bound = []
        bind = self.store.runner.bind
        def capture(*args):
            runner = bind(*args)
            bound.append(runner)
            return runner
        for failed_name in ('ownership.json', 'state.json'):
            def fail(path, data):
                if Path(path).name == failed_name:
                    raise OSError('fixture disk failure')
                return original(path, data)
            with self.subTest(failed_name=failed_name), patch('serve_ebook.atomic_json', side_effect=fail), patch.object(self.store.runner, 'bind', side_effect=capture):
                with self.assertRaises(OSError):
                    self.store.agent_action(job, 'claim', dict(session='old-chat', host='test', model='fixture'))
            self.assertIsNotNone(bound[-1].revoked)
            self.assertNotIn(job, self.store.runners)
            self.assertEqual(self.store.get(job)['state'], 'awaiting_agent')
            self.assertEqual(self.calls, [])

    def test_racing_retry_cannot_have_its_replacement_worker_or_event_retired(self):
        job = self.create()
        self.store.agent_action(job, 'claim', dict(session='old-chat', host='test', model='fixture'))
        self.pending(job, 'old-chat')
        self.store.agent_action(job, 'release', {'session': 'old-chat'})
        self.drain()
        old = self.store.runners[job]
        entered, resume = threading.Event(), threading.Event()
        original = old.condition
        errors = []
        class PausedCondition:
            def __enter__(self):
                entered.set()
                if not resume.wait(3):
                    raise AssertionError('recovery test did not resume')
                return original.__enter__()
            def __exit__(self, *args):
                return original.__exit__(*args)
        def recover():
            try:
                self.recover(job)
            except ValueError as error:
                errors.append(error)
        with patch.object(old, 'condition', PausedCondition()):
            thread = threading.Thread(target=recover)
            thread.start()
            try:
                self.assertTrue(entered.wait(1))
                self.store.agent_action(job, 'retry', {'session': 'old-chat'})
                self.drain()
                self.store.agent_action(job, 'claim', dict(session='old-chat', host='test', model='fixture'))
                self.pending(job, 'old-chat')
                current_event = self.store.events[job]
                current_runner = self.store.runners[job]
                current_worker = self.store.workers[job]
            finally:
                resume.set()
                thread.join(3)
        self.assertFalse(thread.is_alive())
        self.assertEqual(len(errors), 1)
        self.assertFalse(current_event.is_set())
        self.assertIsNone(current_runner.revoked)
        self.assertIs(self.store.workers[job], current_worker)
        self.assertEqual(self.store.get(job)['assistant_session'], 'old-chat')
