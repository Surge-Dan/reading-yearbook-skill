import sys
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))
from serve_ebook import offline_page, workbench_page
from test_book_title import analysis_reply


class ReadingRedesignBrowserTests(unittest.TestCase):
    def test_review_share_keeps_scope_in_footer_without_repeating_full_audit(self):
        a=analysis_reply()
        a.update(input_mode='title',evaluation_limit='非隔离对照',limitations=['很长的审计说明'*50])
        with sync_playwright() as p:
            browser=p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless=True)
            try:
                page=browser.new_page(); page.set_content(offline_page(a,''),wait_until='load')
                result=page.evaluate("""async()=>{const art=ReadingShareArtwork.createDigest({analysis:EBOOK_RESULT.analysis});
                    const pages=await art.pages([{id:'review-0',kind:'review',title:'我的书评',text:'AI书评正文。'}],'3:4');
                    const canvas=await art.render(pages[0],'3:4');
                    return {rows:pages.flatMap(p=>p.rows.map(r=>r.text)).join(''),footer:canvas.readingLayout.text.filter(t=>t.role==='footer').map(t=>t.text).join('')};}""")
                self.assertNotIn('很长的审计说明',result['rows'])
                self.assertIn('未核验全文',result['footer'])
                self.assertNotIn('AI 阅读札记',result['footer'])
                self.assertIn('出处与资料范围见结果页',result['footer'])
                partial=page.evaluate("""async()=>{const a={...EBOOK_RESULT.analysis,input_mode:'upload',evaluation_limit:'',reading_status:{level:'partial'}};
                    const art=ReadingShareArtwork.createDigest({analysis:a});const pages=await art.pages([{id:'r',kind:'review',title:'书评',text:'正文'}],'3:4');
                    const canvas=await art.render(pages[0],'3:4');return canvas.readingLayout.text.filter(t=>t.role==='footer').map(t=>t.text).join('');}""")
                self.assertIn('部分解读',partial)
            finally: browser.close()

    def test_legacy_method_verification_is_retained_at_bottom(self):
        a = analysis_reply()
        a.update(quality_status='needs_review', coverage={'complete':False})
        a.pop('reading_status', None)
        a['methods'] = [{'title':title,'interpretation':'保留使用条件。','verification':{'status':status}}
                        for title,status in [('尚未检查的方法','needs_review'),('仅供参考的方法','reference'),('检查完成的方法','validated')]]
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page()
                page.set_content(offline_page(a, ''), wait_until='load')
                self.assertEqual('', page.locator('#ebookQuality').inner_text())
                for title,label in [('尚未检查的方法','needs_review'),('仅供参考的方法','reference'),('检查完成的方法','validated')]:
                    article = page.locator('[data-reading-section="methods"] article').filter(has=page.get_by_role('heading',name=title,exact=True))
                    self.assertNotIn(label,article.inner_text())
                    self.assertIn(label,page.locator('[data-reading-section="references"]').text_content())
            finally: browser.close()

    def test_review_and_title_stage_names_are_readable(self):
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page()
                for stage, label in [('reading-review','撰写书评'),('title-research','查阅公开资料'),('title-analysis','整理书籍解读')]:
                    job = {'id':'test','state':'awaiting_response','stage':stage}
                    def route_request(route):
                        if '/api/' in route.request.url:
                            route.fulfill(json={'runner':{'available':True,'mode':'current-agent-instructed-tools'},'jobs':[job],'job':job})
                        else:
                            route.fulfill(body=workbench_page({'token':'test'},legacy=True),content_type='text/html')
                    page.route('**/*',route_request)
                    page.goto('http://reading.test',wait_until='networkidle')
                    self.assertIn(label,page.locator('#ebookProgress').inner_text())
                    page.unroute('**/*',route_request)
            finally: browser.close()

    def test_reading_structure_review_copy_and_real_share_renderer(self):
        a = analysis_reply()
        source = dict(a['themes'][0]['sources'][0], source_type='author',url='https://example.org/research/'+'long-location/'*30)
        a.update(input_mode='title', methods=[], cases=[], counterexamples=[], glossary=[], references=[],
                 reading_status={'level':'partial','label':'部分解读','reason':'尚缺关键章节'},
                 insights=[{'title':'先检查条件','explanation':'条件决定方法的用处。','sources':[source]}],
                 review={'status':'ready','paragraphs':[{'text':'我更在意方法停下来的条件。','sources':[source],'quotes':[]},
                                                      {'text':'保留疑问，比过早下结论更有价值。','sources':[source],'quotes':[]}]})
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(viewport={'width':375,'height':812}, reduced_motion='reduce')
                capture = """<script>const realDigest=ReadingShareArtwork.createDigest;ReadingShareArtwork.createDigest=(options)=>{const art=realDigest(options),realPages=art.pages;art.pages=(items,...args)=>{window.renderedShareItems=items;return realPages.call(art,items,...args)};return art;};</script>"""
                html = offline_page(a, '测试正文').replace('<script id="ebook-app-mounted">',capture+'<script id="ebook-app-mounted">')
                page.set_content(html, wait_until='load')
                self.assertEqual(page.locator('#ebookResult > section > h3').all_text_contents(),
                                 ['书籍概览','核心观点','对我的启发','我的书评','参考资料'])
                self.assertIn('部分解读', page.locator('[data-reading-section="references"]').text_content())
                self.assertIn('尚缺关键章节', page.locator('[data-reading-section="references"]').text_content())
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                self.assertEqual(page.evaluate('getComputedStyle(document.documentElement).scrollBehavior'), 'auto')
                review = page.locator('[data-reading-section="review"]')
                self.assertEqual(review.locator('blockquote').count(), 0)
                self.assertNotIn('AI 撰写', review.inner_text())
                page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text;}}})")
                review.get_by_role('button', name='复制这条').first.click()
                copied = page.evaluate('window.copied')
                for text in ('我更在意方法停下来的条件。', '未核验全文'): self.assertIn(text, copied)
                self.assertNotIn('AI 书评', copied)
                self.assertEqual(page.locator('[data-ebook-share="review-0"]').count(), 1)
                page.locator('#ebookShareToggle').click()
                page.wait_for_function("() => !document.getElementById('ebookExportPng').disabled")
                share_text = page.evaluate("renderedShareItems.find(item=>item.id==='review-0').text")
                self.assertEqual('我更在意方法停下来的条件。', share_text)
                for text in (source['quote'],source['url']): self.assertNotIn(text,share_text)
                self.assertIn('我的书评 · 1', page.locator('#ebookPage').inner_text())
                self.assertGreater(page.locator('#ebookCanvas').evaluate('(c)=>c.width'), 0)
                review_page = page.locator('#ebookPage option').filter(has_text='我的书评 · 1').first.get_attribute('value')
                page.locator('#ebookPage').select_option(review_page)
                with page.expect_download() as download:
                    page.locator('#ebookExportPng').click()
                self.assertTrue(download.value.suggested_filename.endswith('.png'))
                self.assertGreater(Path(download.value.path()).stat().st_size, 1000)
                self.assertEqual(page.locator('.ebook-reading-nav a').all_text_contents(), ['书籍概览','核心观点','对我的启发','我的书评','参考资料'])
                page.set_viewport_size({'width':1280,'height':900})
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                self.assertEqual(review.evaluate('(e)=>getComputedStyle(e).opacity'), '1')
                page.locator('.ebook-reading-nav summary').click()
                page.locator('.ebook-reading-nav a').filter(has_text='核心观点').click()
                page.wait_for_function("() => document.querySelector('.ebook-reading-nav a[aria-current]').textContent==='核心观点'", timeout=3000)
                self.assertEqual(page.locator('.ebook-reading-nav').evaluate('(e)=>getComputedStyle(e).position'), 'static')
            finally: browser.close()

    def test_old_result_and_failed_review_remain_readable(self):
        a = analysis_reply()
        a.update(methods=[], cases=[], counterexamples=[], glossary=[], references=[],
                 review={'status':'unavailable','reason':'引用待核查','paragraphs':[]})
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page()
                page.set_content(offline_page(a, ''), wait_until='load')
                self.assertIn('书评暂未生成', page.locator('[data-reading-section="references"]').text_content())
                self.assertEqual(page.locator('[data-ebook-share^="review-"]').count(), 0)
                self.assertEqual(page.get_by_role('heading',name='值得带走的方法',exact=True).count(), 0)
                self.assertEqual(page.get_by_role('heading',name='核心观点',exact=True).count(), 1)
                del a['review']
                a['cases'] = [{'title':'练习','explanation':'练习不能证明原方法有效。','case_origin':'ai_exercise','sources':a['themes'][0]['sources']}]
                page.set_content(offline_page(a, ''), wait_until='load')
                self.assertEqual(page.get_by_role('heading',name='我的书评',exact=True).count(), 0)
                self.assertEqual(page.get_by_role('heading',name='关键案例',exact=True).count(), 1)
                page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text;}}})")
                page.locator('[data-reading-section="cases"]').get_by_role('button',name='复制这条').click()
                self.assertIn('不是原书案例',page.evaluate('window.copied'))
                self.assertIn('所提供正文',page.evaluate('window.copied'))
            finally: browser.close()


if __name__ == '__main__': unittest.main()
