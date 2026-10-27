"""Public examples must remain aligned with the shipped renderer, not a stale deck."""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'reading-yearbook-skill'
DEMO = ROOT / 'examples/reading-html-demo'


class CurrentExampleTests(unittest.TestCase):
    maxDiff = 500
    def test_public_example_uses_current_css_and_inline_scripts(self):
        page = (DEMO / 'index.html').read_text('utf-8')
        expected_css = '\n'.join((ROOT / 'assets' / name).read_text('utf-8')
                                 for name in ('reading-app.css', 'reading-art.css','ebook-app.css'))
        self.assertEqual(re.search(r'<style>(.*?)</style>', page, re.S).group(1).strip(), expected_css.strip())
        for script_id,asset in [('reading-share-mounted','reading-share-art.js'),('ebook-app-mounted','ebook-app.js')]:
            self.assertEqual(re.search(r'<script id="'+script_id+r'">(.*?)</script>',page,re.S).group(1).strip(),(ROOT/'assets'/asset).read_text('utf-8').strip())
        self.assertEqual(re.search(r'<script>(.*?)</script>',page,re.S).group(1).strip(),(ROOT/'assets/reading-app.js').read_text('utf-8').strip())
        self.assertIn('data-reader-mode="readonly"',page)
        self.assertNotIn('id="ebookUpload"',page)
        embedded=json.loads(re.search(r'<script id="reading-data" type="application/json">(.*?)</script>',page,re.S).group(1))
        self.assertEqual(embedded['distillations'][0]['source_mode'],'sample')

    def test_demo_materials_are_fictional_and_statistics_agree(self):
        data = json.loads((DEMO / 'demo-data.json').read_text('utf-8'))
        self.assertEqual(data['source_mode'], 'sample')
        self.assertEqual(data['verification_status'], 'sample_verified')
        self.assertEqual(data['summary']['book_count'], len(data['books']))
        self.assertEqual(data['summary']['total_read_seconds'], sum(data['summary']['monthly_read_seconds']))
        self.assertEqual(data['summary']['total_read_seconds'], sum(b['annual_reading_seconds'] for b in data['books']))
        self.assertEqual(data['summary']['note_count'], sum(len(b['highlights'])+len(b['thoughts']) for b in data['books']))
        self.assertEqual({(bool(b['highlights']), bool(b['thoughts'])) for b in data['books']},
                         {(True, True), (True, False), (False, True), (False, False)})

    def test_export_artifacts_cover_all_pages_with_correct_dimensions(self):
        from PIL import Image
        report = json.loads((DEMO / 'preview-manifest.json').read_text('utf-8'))
        data = json.loads((DEMO / 'demo-data.json').read_text('utf-8'))
        self.assertEqual(report['pages'], len(data['books']) + 4)
        self.assertEqual(report['pages'], len(report['images']))
        self.assertTrue(report['sample_data'])
        self.assertTrue(report['browser_png_matches_preview'])
        self.assertLessEqual(report['max_premultiplied_channel_delta'], 1)
        for row in report['images']:
            with self.subTest(page=row['filename']):
                with Image.open(DEMO / 'images' / row['filename']) as image:
                    image.load()
                    self.assertEqual(image.size, (900, 1200))


if __name__ == '__main__':
    unittest.main()
