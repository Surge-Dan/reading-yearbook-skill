import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'reading-yearbook-skill/scripts'))
from serve_ebook import JobStore, create_server, offline_page
from ebook_agent_bridge import AgentRunner
from test_book_title import analysis_reply


class TitleBrowserTests(unittest.TestCase):
    def test_legacy_browser_submits_title_and_keeps_upload_tab(self):
        with tempfile.TemporaryDirectory() as tmp, sync_playwright() as p:
            store = JobStore(tmp, AgentRunner()); server = create_server(store, legacy_workbench=True)
            thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(viewport={'width':375,'height':812})
                page.goto('http://127.0.0.1:' + str(server.server_port), wait_until='networkidle')
                self.assertEqual(page.locator('#ebookTitleInput').count(), 1, '缺少书名入口')
                page.wait_for_function("() => !document.getElementById('ebookTitleSubmit').disabled")
                page.locator('#ebookTitleInput').fill('测试书')
                page.locator('#ebookAuthorInput').fill('作者')
                page.locator('#ebookTitleSubmit').click()
                page.wait_for_function("() => document.getElementById('ebookStatus').textContent.includes('书名已接收')")
                self.assertEqual(store.state()['jobs'][0]['book_query']['title'], '测试书')
                page.locator('#ebookUploadTab').click()
                self.assertTrue(page.locator('#ebookUploadPanel').is_visible())
                self.assertFalse(page.evaluate('document.documentElement.scrollWidth>innerWidth'))
                page.locator('#ebookCancel').click()
                page.wait_for_function("() => document.getElementById('ebookStatus').textContent.includes('已取消')")
                self.assertTrue(page.locator('#ebookTitleSubmit').is_enabled(), '取消后必须能创建下一本书')
            finally:
                browser.close(); server.shutdown(); server.server_close(); store.close(); thread.join(2)

    def test_title_offline_copy_and_every_share_footer_keeps_scope(self):
        a = analysis_reply()
        a.update(input_mode='title',source_notice='基于公开资料，未核验全文',quality_status='needs_review',
                 coverage={'complete':False,'scope_note':'未核验全文','sources_read':1},references=[],bibliography=[],
                 evaluation_limit='未进行独立任务增益验证')
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page()
                page.set_content(offline_page(a, '基于公开资料，未核验全文'), wait_until='load')
                self.assertIn('未核验全文', page.locator('[data-reading-section="references"]').text_content())
                footers = page.evaluate("""async () => {const art=ReadingShareArtwork.createDigest({analysis:EBOOK_RESULT.analysis});const out=[];for(const ratio of ['1:1','3:4','4:5']){const pages=await art.pages([{id:'x',title:'观点',text:'测试内容'.repeat(1000)}],ratio);for(const p of pages){const c=await art.render(p,ratio);out.push(c.readingLayout.text.filter(t=>t.role==='footer').map(t=>t.text).join(' '));}}return out;}""")
                self.assertTrue(all('未核验全文' in text for text in footers))
            finally: browser.close()

    def test_single_copy_keeps_content_and_case_origin_sources_stay_in_references(self):
        a = analysis_reply(); source = a['themes'][0]['sources'][0]
        source.update(source_type='author',url='https://example.org/book')
        method = {'id':'m1','title':'检查','trigger':'条件明确','steps':['记录问题'],'boundaries':['条件不明停止'],
                  'interpretation':'比较方案','example':'AI 演练：检查清单','sources':[source],
                  'verification':{'status':'needs_review'}}
        a.update(input_mode='title',quality_status='needs_review',coverage={},references=[],decision_rules=[dict(method,method_id='m1')],
                 cases=[{'title':'练习','explanation':'演练一次记录。','case_origin':'ai_exercise','sources':[source]}])
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(); page.set_content(offline_page(a, '未核验全文'), wait_until='load')
                page.evaluate("Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>{window.copied=text;}}})")
                decision = page.locator('#ebookResult details').filter(has=page.locator('summary',has_text='决策速查'))
                decision.locator(':scope > summary').click()
                decision.get_by_role('button',name='复制这条').click()
                with self.subTest('decision content'):
                    copied = page.evaluate('window.copied')
                    for value in ('比较方案','记录问题','未核验全文'): self.assertIn(value, copied)
                    self.assertNotIn(source['url'], copied)
                    self.assertIn(source['quote'],page.locator('[data-reading-section="references"]').text_content())
                case = page.locator('#ebookResult article').filter(has=page.get_by_role('heading',name='练习',exact=True))
                case.get_by_role('button',name='复制这条').click()
                with self.subTest('case origin'): self.assertIn('不是原书案例', page.evaluate('window.copied'))
            finally: browser.close()


if __name__ == '__main__': unittest.main()
