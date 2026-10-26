import subprocess
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))
from ebook_runner import CLIRunner, create_runner
from ebook_pipeline import distill, _stage_source_gate
from test_ebook_core import ContractRunner


class RunnerTests(unittest.TestCase):
    def test_codex_call_disables_optional_external_execution_capabilities(self):
        commands=[]
        class Process:
            pid=123
            returncode=0
            def communicate(self, **kwargs): return '', ''
        def popen(args, **kwargs):
            commands.append(args)
            Path(args[args.index('--output-last-message')+1]).write_text('{"ready":true}',encoding='utf-8')
            return Process()
        with patch('ebook_runner.shutil.which',return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen',side_effect=popen):
            self.assertEqual(CLIRunner('codex').generate('inert source'),{'ready':True})
        options={commands[0][i+1] for i,arg in enumerate(commands[0][:-1]) if arg=='-c'}
        for feature in ('multi_agent','apps','plugins','hooks','browser_use','computer_use','image_generation','unbounded_connection_retries'):
            self.assertIn('features.'+feature+'=false',options)
        self.assertIn('features.shell_tool=false',options)
        self.assertIn('mcp_servers={}',options)
        self.assertIn('web_search="disabled"',options)

    def test_native_api_403_survives_success_subtype_without_leaking_response(self):
        class Process:
            pid = 123
            returncode = 1
            def communicate(self, **kwargs):
                return json.dumps({'type':'result','subtype':'success','is_error':True,
                                   'result':'API Error: 403 {"error":{"type":"api_error","message":"private-book-secret"}}'}), ''
        with patch('ebook_runner.shutil.which', return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen', return_value=Process()):
            runner = CLIRunner('claude')
            with self.assertRaises(ValueError) as caught: runner.generate('source')
            self.assertEqual(caught.exception.diagnostic['category'], 'permission')
            self.assertEqual(caught.exception.diagnostic['api_status'], 403)
            self.assertEqual(caught.exception.diagnostic['cli_error_subtype'], 'success')
            self.assertNotIn('private-book-secret', str(caught.exception) + str(caught.exception.diagnostic))

    def test_native_claude_error_envelope_is_classified_without_exposing_text(self):
        class Process:
            pid = 123
            returncode = 1
            def communicate(self, **kwargs):
                return json.dumps({'type':'result','subtype':'error_during_execution','is_error':True,
                                   'errors':['Unable to connect to API: ECONNRESET private-book-secret']}), ''
        with patch('ebook_runner.shutil.which', return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen', return_value=Process()):
            runner = CLIRunner('claude')
            with self.assertRaises(ValueError) as caught:
                runner.generate('private-book-secret')
            self.assertEqual(caught.exception.diagnostic['category'], 'network')
            self.assertEqual(caught.exception.diagnostic['cli_error_subtype'], 'error_during_execution')
            self.assertNotIn('private-book-secret', str(caught.exception) + str(caught.exception.diagnostic))

    def test_claude_structured_output_retry_limit_is_not_generic_connection_failure(self):
        class Process:
            pid = 123
            returncode = 1
            def communicate(self, **kwargs):
                return json.dumps({'type':'result','subtype':'error_max_structured_output_retries','is_error':True,
                                   'errors':['private-book-secret']}), ''
        with patch('ebook_runner.shutil.which', return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen', return_value=Process()):
            runner = CLIRunner('claude')
            with self.assertRaises(ValueError) as caught: runner.generate('private-book-secret')
            self.assertEqual(caught.exception.diagnostic['category'], 'structured_output')
            self.assertIn('结构化', str(caught.exception))
            self.assertNotIn('private-book-secret', str(caught.exception.diagnostic))

    def test_successful_claude_model_text_cannot_spoof_error_diagnostic(self):
        class Process:
            pid = 123
            returncode = 0
            def communicate(self, **kwargs):
                return json.dumps({'type':'result','subtype':'success','is_error':False,
                                   'result':'API Error: 429', 'structured_output':{'ready':True}}), ''
        with patch('ebook_runner.shutil.which', return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen', return_value=Process()):
            runner = CLIRunner('claude')
            self.assertEqual(runner.generate('source'), {'ready':True})
            self.assertEqual(runner.last_diagnostic['category'], 'unclassified')
            self.assertNotIn('cli_error_subtype', runner.last_diagnostic)

    def test_source_gate_restores_only_unambiguous_terminal_period(self):
        citation = {'element_id':'e1','quote':'必以全爭於天下。','location':'model location'}
        original = '必以全爭於天下，故兵不頓而利可全。'
        _stage_source_gate({'sources':[citation]}, [{'element_id':'e1','text':original,'location':'chapter 3'}])
        self.assertEqual(citation['quote'], '必以全爭於天下，')
        self.assertEqual(citation['source_adjustment']['original_quote'], '必以全爭於天下。')
        self.assertEqual(citation['location'], 'chapter 3')
        for text, quote in [('必以全爭於天下？','必以全爭於天下。'),('必以全爭於天下，必以全爭於天下；','必以全爭於天下。'),('必以全爭於天下，','必以全爭于天下。')]:
            with self.assertRaises(ValueError):
                _stage_source_gate({'sources':[{'element_id':'e1','quote':quote,'location':'x'}]}, [{'element_id':'e1','text':text,'location':'x'}])

    def test_source_diagnostic_can_recover_only_after_full_contract_validation(self):
        class Runner(ContractRunner):
            calls_to_model = 0
            def generate(self, prompt, schema=None, cancel_event=None):
                self.calls_to_model += 1
                value = super().generate(prompt, schema, cancel_event)
                if 'OUTPUT_CONTRACT:stage0:' in prompt:
                    value['themes'][0]['sources'][0]['quote'] = '必以全爭於天下。'
                return value
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'book.txt'; source.write_text('必以全爭於天下，故兵不頓而利可全。', 'utf-8')
            output = Path(tmp) / 'out'; runner = Runner()
            # Retain a genuine returned stage as failed diagnostics using the
            # previous strict gate, then exercise the new full validation path.
            with patch('ebook_pipeline._restore_terminal_punctuation', return_value=None):
                with self.assertRaises(ValueError): distill(source, output, runner)
            count = runner.calls_to_model
            result = distill(source, output, runner)
            self.assertEqual(result['quality_status'], 'completed')
            self.assertEqual(runner.calls_to_model-count, 7)  # One joint extraction plus the cached review stage.
    def test_stage_timeout_is_bounded(self):
        for seconds in (0, 29, 901):
            with self.assertRaisesRegex(ValueError, '30.*900'):
                create_runner('codex', timeout=seconds)
        self.assertEqual(create_runner('codex', timeout=600).timeout, 600)

    def test_timeout_reports_only_safe_diagnostic_metadata(self):
        class Process:
            pid = 123
            returncode = -1
            calls = 0
            def communicate(self, **kwargs):
                self.calls += 1
                if self.calls == 1:
                    raise subprocess.TimeoutExpired('fake-cli', .2)
                return 'private answer', 'private-book-secret\n2026-10-08T00:00:00Z ERROR codex_core::client: HTTP 429 rate limit\n'
            def kill(self):
                pass
        with patch('ebook_runner.shutil.which', return_value='fake-cli.exe'), \
             patch('ebook_runner.subprocess.Popen', return_value=Process()), \
             patch('ebook_runner.subprocess.run'), \
             patch('ebook_runner.time.monotonic', side_effect=[0, 31, 31]):
            runner = CLIRunner('codex', timeout=30)
            with self.assertRaises(ValueError) as caught:
                runner.generate('private-book-secret')
            diagnostic = caught.exception.diagnostic
            self.assertEqual(diagnostic['category'], 'rate_limit')
            self.assertEqual(diagnostic['elapsed_seconds'], 31)
            self.assertGreater(diagnostic['stderr_bytes'], 0)
            self.assertNotIn('private-book-secret', str(diagnostic) + str(caught.exception))

    def test_timeout_change_reuses_semantically_valid_stage_cache(self):
        class Runner(ContractRunner):
            timeout = 180
            def info(self):
                return dict(super().info(), timeout=self.timeout)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'book.txt'
            source.write_text('原文', 'utf-8')
            runner = Runner()
            distill(source, Path(tmp) / 'out', runner)
            count = len(runner.calls)
            runner.timeout = 600
            distill(source, Path(tmp) / 'out', runner)
            self.assertEqual(len(runner.calls), count)

    def test_model_stages_receive_required_top_level_json_schema(self):
        class Runner(ContractRunner):
            schemas = []
            def generate(self, prompt, schema=None, cancel_event=None):
                self.schemas.append(schema)
                return super().generate(prompt, schema, cancel_event)
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'book.txt'
            source.write_text('原文', 'utf-8')
            runner = Runner()
            distill(source, Path(tmp) / 'out', runner)
            for schema in runner.schemas:
                self.assertIsInstance(schema, dict)
                self.assertTrue(schema['required'], 'Generic object schema permits an empty successful output')
                self.assertEqual(set(schema['required']), set(schema['properties']))

    def test_invalid_source_output_is_diagnostic_only_not_reused_cache(self):
        class Runner(ContractRunner):
            def generate(self, prompt, schema=None, cancel_event=None):
                self.assertion_prompt = prompt
                value = super().generate(prompt, schema, cancel_event)
                value['themes'][0]['sources'][0]['quote'] = '不存在于正文的引用'
                return value
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'book.txt'
            source.write_text('原文', 'utf-8')
            runner = Runner()
            output = Path(tmp) / 'out'
            with self.assertRaises(ValueError) as caught:
                distill(source, output, runner)
            self.assertFalse(caught.exception.diagnostic['exact_quote_match'])
            files = list((output / '.diagnostics').glob('*.json'))
            self.assertEqual(len(files), 1)
            self.assertEqual(json.loads(files[0].read_text('utf-8'))['stage'], 'stage0-map')
            self.assertEqual(list((output / '.cache').glob('*.json')), [])
            self.assertFalse((output / 'analysis.json').exists())
            self.assertIn('150 Chinese characters', runner.assertion_prompt)


if __name__ == '__main__':
    unittest.main()
