import sys
import tempfile
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import adapt_data, build_html
from test_reading_html import fixture


class ReadingChartDesignTests(unittest.TestCase):
    def test_large_category_marks_are_bounded_and_zero_is_not_missing(self):
        raw = fixture()
        raw['books'] = [{'book_id':str(i),'title':'测试书'+str(i),'category':'方法',
                         'reading_seconds':0 if i==0 else None} for i in range(221)]
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            path = Path(tmp)/'index.html'; build_html(adapt_data(raw),path)
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            try:
                page = browser.new_page(reduced_motion='reduce'); page.goto(path.as_uri(),wait_until='load')
                self.assertLessEqual(page.locator('[data-spine-value]').count(),10)
                self.assertEqual(page.locator('[data-spine-value]').evaluate_all('(ns)=>ns.reduce((s,n)=>s+Number(n.dataset.spineValue),0)'),221)
                self.assertEqual(page.locator('.investment-row').count(),1)
                self.assertEqual(float(page.locator('.duration-fill').get_attribute('width')),0)
                page.locator('[data-category]').focus(); page.keyboard.press('Enter')
                self.assertEqual(page.locator('[data-category]').get_attribute('aria-pressed'),'true')
            finally:
                browser.close()

    def test_spines_and_duration_bars_keep_exact_data_and_interactions(self):
        raw = fixture()
        for book, seconds in zip(raw['books'], (3600,1815,None)):
            book['reading_seconds'] = seconds
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            path = Path(tmp)/'index.html'; build_html(adapt_data(raw), path)
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(reduced_motion='reduce')
                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(path.as_uri(), wait_until='load')
                self.assertEqual(page.locator('[data-spine-value]').count(), 3, '分类应绘制书脊实体')
                self.assertEqual(page.locator('.category-count').all_text_contents(), ['2','1'])
                rows = page.locator('.investment-row')
                self.assertEqual(rows.count(), 2)
                values = rows.evaluate_all('(ns)=>ns.map(n=>({seconds:Number(n.dataset.seconds),width:Number(n.querySelector(".duration-fill").getAttribute("width"))}))')
                self.assertAlmostEqual(values[1]['width']/values[0]['width'], 1815/3600)
                self.assertEqual(rows.locator('.investment-cover').count(), 2)
                for width in (375,768,1440):
                    page.set_viewport_size({'width':width,'height':900})
                    self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                page.locator('[data-category="方法"]').click()
                self.assertEqual(page.locator('[data-category="方法"]').get_attribute('aria-pressed'), 'true')
                rows.first.click()
                self.assertTrue(page.locator('#detail').is_visible())
                page.locator('#detail').evaluate('(e)=>e.close()')
                for ratio in ('1:1','3:4','4:5'):
                    layouts = page.evaluate("""async ratio=>{
                        const data=JSON.parse(document.querySelector('#reading-data').textContent),art=JSON.parse(document.querySelector('#reading-art').textContent);
                        const loadImage=src=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;});
                        const renderer=ReadingShareArtwork.create({data,art,loadImage}),out=[];
                        for(const kind of ['distribution','stats'])out.push((await renderer.render({id:kind,kind},ratio)).readingLayout);
                        return out;
                    }""", ratio)
                    categories = [c for c in layouts[0]['charts'] if c['kind']=='category']
                    self.assertEqual(sum(c['count'] for c in categories), 3)
                    self.assertTrue(all(c.get('encoding')=='book-spines' for c in categories))
                    if ratio != '1:1':
                        self.assertTrue(any(c['kind']=='duration-bar' for c in layouts[1]['charts']))
                self.assertEqual(errors, [])
            finally:
                browser.close()


if __name__ == '__main__': unittest.main()
