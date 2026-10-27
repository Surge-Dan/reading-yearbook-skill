import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data, build_html
from distillation_result import make_bundle
from test_distillation_result import fixture
import generate_reading_html as generator
import build_reading_html as builder
from serve_ebook import workbench_page


def bundle(sample=False, title='受控短篇'):
    analysis, document = fixture()
    analysis['book']['title'] = document['book']['title'] = title
    if sample:
        document['source_mode'] = 'sample'
    return make_bundle(analysis, document)


def report_data(packages=None, sample=False):
    data = adapt_data({'year': 2026, 'source_mode': 'sample' if sample else 'real',
                       'summary': {'book_count': 0}, 'books': []})
    if packages is not None:
        data['distillations'] = packages
    return data


class ReportReaderTests(unittest.TestCase):
    def test_deliver_gate_runs_before_writing_output_or_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index.html'; state=Path(tmp)/'state.json'
            path.write_text('previous','utf-8')
            with self.assertRaisesRegex(ValueError,'先蒸馏至少一本'):
                generator.deliver({}, {}, {}, path, state_path=state)
            self.assertEqual(path.read_text('utf-8'),'previous')
            self.assertFalse(state.exists())

    def test_repeatable_cli_loads_both_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); source=root/'input.json'; output=root/'index.html'
            source.write_text(json.dumps(report_data()),'utf-8')
            arguments=['build','--input',str(source),'--output',str(output)]
            for i in range(2):
                package=root/('distillation'+str(i)+'.json')
                package.write_text(json.dumps(bundle(title='受控短篇'+str(i))),'utf-8')
                arguments+=['--distillation',str(package)]
            with patch('sys.argv',arguments),patch('builtins.print'):
                self.assertEqual(builder.main(),0)
            page=output.read_text('utf-8')
            embedded=json.loads(page.split('<script id="reading-data" type="application/json">')[1].split('</script>')[0])
            self.assertEqual(len(embedded['distillations']),2)

    def test_gate_preserves_existing_report_for_empty_bad_or_sample_real(self):
        invalid = bundle(); invalid['digest'] = 'tampered'
        for packages in ([], [invalid], [bundle(sample=True)], [bundle(), bundle(sample=True)]):
            with self.subTest(packages=len(packages)), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / 'index.html'; path.write_text('previous', encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '先蒸馏至少一本|结果包|sample|示例|完整性'):
                    build_html(report_data(packages), path)
                self.assertEqual(path.read_text('utf-8'), 'previous')

    def test_one_and_multiple_bundles_are_embedded_without_changing_stats(self):
        for count in (1, 2):
            packages = [bundle(title='受控短篇' + str(i)) for i in range(count)]
            with tempfile.TemporaryDirectory() as tmp:
                data = report_data(packages); before = copy.deepcopy(data['summary'])
                path = Path(tmp) / 'index.html'; build_html(data, path)
                page = path.read_text('utf-8')
                embedded = json.loads(page.split('<script id="reading-data" type="application/json">')[1].split('</script>')[0])
                self.assertEqual(embedded['distillations'], packages)
                self.assertEqual(embedded['summary'], before)
                self.assertIn('data-reader-mode="readonly"', page)
                self.assertNotIn('id="ebookUpload"', page)

    def test_adapter_retains_validated_bundle_and_escapes_script_injection(self):
        raw = report_data([bundle(title='</script><script>window.injected=1</script>')])
        data = adapt_data(raw)
        self.assertEqual(data.get('distillations'), raw['distillations'])
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'index.html'; build_html(data, path)
            self.assertNotIn('</script><script>window.injected=1', path.read_text('utf-8'))

    def test_sample_report_accepts_only_sample_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            build_html(report_data([bundle(sample=True)], sample=True), Path(tmp) / 'sample.html')
            with self.assertRaises(ValueError):
                build_html(report_data([bundle()], sample=True), Path(tmp) / 'mixed.html')

    def test_generator_checks_before_credentials_resources_or_collection(self):
        with tempfile.TemporaryDirectory() as tmp, patch('sys.argv', ['generate', '--output', str(Path(tmp)/'index.html')]), patch.dict('os.environ', {'WEREAD_API_KEY':'controlled'}), patch.object(generator, 'collect_snapshot') as collect, patch('builtins.print') as output:
            self.assertEqual(generator.main(), 2)
            collect.assert_not_called()
            self.assertIn('先蒸馏至少一本', str(output.call_args))

    def test_invalid_package_cli_returns_actionable_error_without_collection_or_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); package=root/'bad.json'; package.write_text('{}','utf-8')
            source=root/'input.json';source.write_text(json.dumps(report_data()),'utf-8')
            target=root/'index.html';target.write_text('previous','utf-8')
            for module,arguments in [(generator,['generate','--output',str(target),'--distillation',str(package)]),
                                     (builder,['build','--input',str(source),'--output',str(target),'--distillation',str(package)])]:
                with self.subTest(module=module.__name__),patch('sys.argv',arguments),patch.object(generator,'collect_snapshot') as collect,patch('builtins.print') as output:
                    self.assertEqual(module.main(),2)
                    collect.assert_not_called()
                    self.assertIn('先蒸馏至少一本',str(output.call_args))
                    self.assertEqual(target.read_text('utf-8'),'previous')

    def test_default_server_reader_has_no_task_controls_or_credentials(self):
        page = workbench_page({'token':'READER-TOKEN', 'output':'PRIVATE-PATH'}, {'analysis':bundle()['analysis'], 'digest':''})
        self.assertIn('data-reader-mode="readonly"', page)
        for text in ('id="ebookUpload"','id="ebookTask"','READER-TOKEN','PRIVATE-PATH'):
            self.assertNotIn(text, page)

    def test_legacy_report_without_bundle_still_opens_and_keeps_its_result(self):
        annual=report_data(); annual.pop('distillations',None)
        result={'analysis':bundle()['analysis'],'digest':'old readable result'}
        legacy=('<html><head><script id="ebook-config">window.EBOOK_CONFIG={"token":"OLD-TOKEN"};window.EBOOK_RESULT='+json.dumps(result)+'</script></head><body><main><div>ANNUAL_RECORDS</div></main><script id="reading-data" type="application/json">'+json.dumps(annual)+'</script></body></html>')
        legacy=legacy.replace('</body>','<script id="reading-share-mounted">window.STALE_SHARE=true;</script></body>')
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.html';path.write_text(legacy,'utf-8')
            page=workbench_page(yearbook=path)
            self.assertIn('ANNUAL_RECORDS',page)
            self.assertIn('old readable result',page)
            self.assertNotIn('OLD-TOKEN',page)
            self.assertNotIn('id="ebookUpload"',page)
            self.assertFalse('window.STALE_SHARE' in page,'old annual report must use current shared reader exporter')
            self.assertEqual(path.read_text('utf-8'),legacy)

    def test_legacy_developer_workbench_requires_explicit_opt_in(self):
        page=workbench_page({'token':'developer-token'},legacy=True)
        self.assertIn('id="ebookUpload"',page)
        self.assertIn('developer-token',page)


if __name__ == '__main__':
    unittest.main()
