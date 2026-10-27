import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data, build_html
from generate_reading_html import deliver, main
from serve_ebook import workbench_page
from test_reading_html import fixture
from test_reading_html_delivery import snapshot
from test_report_reader import bundle


class CoverDeliveryGateTests(unittest.TestCase):
    def test_missing_and_invalid_embedded_covers_do_not_block_report(self):
        for invalid in ('', 'data:image/png;base64,AAAA'):
            raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]
            data=adapt_data(raw)
            for book in data['books']: book['cover']=invalid
            with self.subTest(invalid=invalid), tempfile.TemporaryDirectory() as tmp:
                target=Path(tmp)/'index.html'
                result=build_html(data,target)
                self.assertEqual(result['output'],str(target))
                self.assertEqual(result['missing_covers'],3)
                self.assertTrue(all(not b['cover'] for b in data['books']))
                page=workbench_page(yearbook=target)
                self.assertTrue('reading-data' in page)
                self.assertFalse('data-yearbook-blocked="true"' in page)
                self.assertFalse('data-reading-draft="true"' in page)

    def test_invalid_cover_file_delivers_usable_partial_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); cover=root/'bad.png'; cover.write_bytes(b'bad image')
            target=root/'index.html'
            result=deliver(snapshot(),{'year':2026,'books':[]},{'one':str(cover)},target,distillations=[bundle()])
            self.assertEqual(result['status'],'partial')
            self.assertEqual(result['missing_books'][0]['reason'],'invalid')
            self.assertEqual(result['output'],str(target))
            self.assertTrue('reading-data' in workbench_page(yearbook=target))

    def test_cli_delivers_partial_report_when_cover_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name,value in [('snapshot.json',snapshot()),('materials.json',{'year':2026,'books':[]}),('covers.json',{})]:
                (root/name).write_text(json.dumps(value),encoding='utf-8')
            args=['generate','--year','2026','--annual-snapshot',str(root/'snapshot.json'),
                  '--materials',str(root/'materials.json'),'--covers',str(root/'covers.json'),'--output',str(root/'index.html')]
            package=root/'distillation.json';package.write_text(json.dumps(bundle()),'utf-8')
            args+=['--distillation',str(package)]
            with patch('sys.argv',args),patch('builtins.print') as output:
                self.assertEqual(main(),3)
                self.assertEqual(json.loads(output.call_args.args[0])['status'],'partial')
            self.assertTrue((root/'index.html').exists())

    def test_legacy_missing_cover_report_stays_available(self):
        raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]
        legacy='<html><head></head><body><main><script id="reading-data">'+json.dumps(adapt_data(raw))+'</script><div>ANNUAL_SHELF</div></main></body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'index-draft.html'; path.write_text(legacy,encoding='utf-8')
            page=workbench_page(yearbook=path)
            self.assertTrue('ANNUAL_SHELF' in page)
            self.assertTrue('data-reader-mode="readonly"' in page)
            self.assertFalse('id="ebookTitleInput"' in page)
            self.assertEqual(path.read_text('utf-8'),legacy)

    def test_explicit_strict_mode_preserves_previous_file(self):
        raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
            with self.assertRaises(ValueError): build_html(adapt_data(raw),target,require_all_covers=True)
            self.assertEqual(target.read_text('utf-8'),'previous final')

    def test_explicit_draft_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'index.html'; target.write_text('previous final',encoding='utf-8')
            result=deliver(snapshot(),{'year':2026,'books':[]},{},target,allow_draft=True,distillations=[bundle()])
            self.assertEqual(Path(result['output']).name,'index-draft.html')
            self.assertEqual(target.read_text('utf-8'),'previous final')

    def test_invalid_report_structure_is_still_blocked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broken.html'; path.write_text('<main>UNVERIFIED_REPORT</main>',encoding='utf-8')
            page=workbench_page(yearbook=path)
            self.assertFalse('UNVERIFIED_REPORT' in page)
            self.assertTrue('data-yearbook-blocked="true"' in page)

    def test_valid_cover_is_preserved_when_other_covers_are_missing(self):
        raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]; data=adapt_data(raw)
        image='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAIAAAADCAIAAAA2iEnWAAAAFElEQVR4nGP8/ukpAwMDEwMYQCkANbAC1LhAEWwAAAAASUVORK5CYII='
        data['books'][0]['cover']=image
        with tempfile.TemporaryDirectory() as tmp:
            result=build_html(data,Path(tmp)/'index.html')
            self.assertEqual(result['missing_covers'],2)
            self.assertEqual(data['books'][0]['cover'],image)

    def test_legacy_bad_cover_is_cleared_in_share_data_without_changing_source(self):
        from cover_contract import YearbookData
        raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]; data=adapt_data(raw)
        data['books'][0]['cover']='data:image/png;base64,AAAA'
        legacy='<html><head></head><body><main><script id="reading-data">'+json.dumps(data)+'</script></main></body></html>'
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'old.html'; path.write_text(legacy,encoding='utf-8')
            page=workbench_page(yearbook=path)
            parser=YearbookData(); parser.feed(page)
            self.assertEqual(json.loads(''.join(parser.parts))['books'][0]['cover'],'')
            self.assertEqual(path.read_text('utf-8'),legacy)

    def test_structurally_broken_book_does_not_crash_frontend(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'broken.html'
            path.write_text('<main><script id="reading-data">{"books":[{}]}</script></main>',encoding='utf-8')
            self.assertTrue('data-yearbook-blocked="true"' in workbench_page(yearbook=path))

    def test_visual_refresh_accepts_placeholder_metadata_without_losing_records(self):
        from cover_contract import YearbookData
        from refresh_reading_chart_preview import main as refresh
        raw=fixture(); raw['source_mode']='live'; raw['distillations']=[bundle()]
        data=adapt_data(raw)
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/'old.html'; target=Path(tmp)/'new.html'
            build_html(data,source)
            page=source.read_text('utf-8'); parser=YearbookData(); parser.feed(page)
            data['collection_status']={'complete':True,'errors':[],'message':''}
            source.write_text(page.replace(''.join(parser.parts),json.dumps(data)),encoding='utf-8')
            with patch('sys.argv',['refresh','--source',str(source),'--output',str(target),'--update-source']),patch('builtins.print'):
                refresh()
            parser=YearbookData(); parser.feed(source.read_text('utf-8'))
            updated=json.loads(''.join(parser.parts))
            self.assertEqual(updated['books'],data['books'])
            self.assertEqual(updated['summary'],data['summary'])


if __name__=='__main__': unittest.main()
