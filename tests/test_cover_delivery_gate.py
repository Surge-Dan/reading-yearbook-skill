import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data, build_html
from generate_reading_html import deliver
from serve_ebook import workbench_page
from test_reading_html import fixture
from test_reading_html_delivery import snapshot


class CoverDeliveryGateTests(unittest.TestCase):
    def test_real_build_blocks_missing_and_invalid_embedded_covers_before_overwrite(self):
        for invalid in ('', 'data:image/png;base64,AAAA'):
            raw = fixture(); raw['source_mode'] = 'live'
            data = adapt_data(raw)
            for book in data['books']: book['cover'] = invalid
            with tempfile.TemporaryDirectory() as tmp:
                target = Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
                with self.subTest(invalid=invalid), self.assertRaises(ValueError): build_html(data,target)
                self.assertTrue(target.read_text('utf-8')=='previous final')

    def test_delivery_is_blocked_without_silently_publishing_a_draft(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
            result = deliver(snapshot(),{'year':2026,'books':[]},{},target)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(result['missing_covers'],1)
            self.assertIsNone(result['output'])
            self.assertEqual(target.read_text('utf-8'),'previous final')
            self.assertFalse(target.with_name('index-draft.html').exists())

    def test_invalid_cover_file_is_not_treated_as_complete_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); cover=root/'bad.png'; cover.write_bytes(b'not an image')
            target=root/'index.html'; target.write_text('previous final',encoding='utf-8')
            result=deliver(snapshot(),{'year':2026,'books':[]},{'one':str(cover)},target)
            self.assertEqual(result['status'],'blocked')
            self.assertEqual(result['missing_books'][0]['reason'],'invalid')
            self.assertEqual(target.read_text('utf-8'),'previous final')

    def test_cli_returns_blocked_exit_code_for_missing_covers(self):
        from generate_reading_html import main
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,value in [('snapshot.json',snapshot()),('materials.json',{'year':2026,'books':[]}),('covers.json',{})]:
                (root/name).write_text(json.dumps(value),encoding='utf-8')
            args=['generate','--year','2026','--annual-snapshot',str(root/'snapshot.json'),
                  '--materials',str(root/'materials.json'),'--covers',str(root/'covers.json'),'--output',str(root/'index.html')]
            with patch('sys.argv',args),patch('builtins.print') as output:
                self.assertEqual(main(),2)
                self.assertEqual(json.loads(output.call_args.args[0])['status'],'blocked')
            self.assertFalse((root/'index.html').exists())

    def test_legacy_missing_cover_report_is_not_exposed_as_workbench_home(self):
        raw = fixture(); raw['source_mode'] = 'live'
        raw['collection_status'] = {'complete':True}
        data = adapt_data(raw)
        legacy = '<html><head></head><body><main><script id="reading-data" type="application/json">'+json.dumps(data)+'</script><div id="books">INCOMPLETE_SHELF</div></main></body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'index-draft.html'; path.write_text(legacy,encoding='utf-8')
            page = workbench_page({'token':'test'},yearbook=path)
            self.assertFalse('INCOMPLETE_SHELF' in page)
            self.assertIn('封面',page)
            self.assertIn('ebookTitleInput',page)
            self.assertEqual(path.read_text('utf-8'),legacy)

    def test_explicit_draft_is_marked_and_still_rejected_as_workbench_home(self):
        raw = fixture(); raw['source_mode'] = 'live'
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index-draft.html'
            build_html(adapt_data(raw),target,allow_draft=True)
            page=target.read_text('utf-8')
            self.assertTrue('data-reading-draft="true"' in page)
            self.assertTrue('data-yearbook-blocked="true"' in workbench_page(yearbook=target))

    def test_explicit_draft_delivery_does_not_replace_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
            result=deliver(snapshot(),{'year':2026,'books':[]},{},target,allow_draft=True)
            self.assertEqual(result['status'],'partial')
            self.assertTrue('data-reading-draft="true"' in Path(result['output']).read_text('utf-8'))
            self.assertEqual(target.read_text('utf-8'),'previous final')

    def test_builder_draft_cannot_overwrite_a_final_name(self):
        raw=fixture(); raw['source_mode']='live'
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
            result=build_html(adapt_data(raw),target,allow_draft=True)
            self.assertEqual(Path(result['output']).name,'index-draft.html')
            self.assertTrue(target.read_text('utf-8')=='previous final')

    def test_visual_refresh_cannot_overwrite_or_publish_legacy_draft(self):
        sys.path.insert(0,str(ROOT/'tests'))
        from refresh_reading_chart_preview import main as refresh
        raw=fixture(); raw['source_mode']='live'
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'old-draft.html'; target=Path(tmp)/'new.html'
            build_html(adapt_data(raw),source,allow_draft=True)
            before=source.read_bytes()
            with patch('sys.argv',['refresh','--source',str(source),'--output',str(target),'--update-source']):
                with self.assertRaises(ValueError): refresh()
            self.assertEqual(source.read_bytes(),before)
            self.assertFalse(target.exists())

    def test_legacy_without_verifiable_payload_is_not_mounted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'legacy.html'
            path.write_text('<html><head></head><body><main>UNVERIFIED_REPORT</main></body></html>',encoding='utf-8')
            page=workbench_page(yearbook=path)
            self.assertFalse('UNVERIFIED_REPORT' in page)
            self.assertTrue('data-yearbook-blocked="true"' in page)

    def test_complete_embedded_cover_and_sample_remain_usable(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp)/'index.html'
            sample = adapt_data(fixture()); build_html(sample,target)
            self.assertIn('reading-data',workbench_page(yearbook=target))
            raw = fixture(); raw['source_mode'] = 'live'; data = adapt_data(raw)
            image = 'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAIAAAA2iEnWAAAAFElEQVR4nGP8/ukpAwMDEwMYQCkANbAC1LhAEWwAAAAASUVORK5CYII='
            for book in data['books']: book['cover'] = image
            build_html(data,target)
            self.assertIn('reading-data',workbench_page(yearbook=target))


if __name__ == '__main__': unittest.main()
