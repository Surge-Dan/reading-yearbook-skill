"""Rebuild an existing local yearbook without recollecting personal data."""
import argparse
import copy
import json
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'reading-yearbook-skill/scripts'))
from build_reading_html import build_html
from cover_contract import missing_covers


class ReadingData(HTMLParser):
    def __init__(self, element_id='reading-data'):
        super().__init__(); self.active = False; self.parts = []; self.element_id = element_id
    def handle_starttag(self, tag, attrs):
        if tag == 'script' and dict(attrs).get('id') == self.element_id: self.active = True
    def handle_endtag(self, tag):
        if tag == 'script': self.active = False
    def handle_data(self, data):
        if self.active: self.parts.append(data)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--update-source', action='store_true')
    parser.add_argument('--screenshots', action='store_true')
    args = parser.parse_args()
    source = args.source.resolve(); target = args.output.resolve()
    if source == target: raise ValueError('预览与源文件必须分开，验证后再更新')
    data_parser = ReadingData(); data_parser.feed(source.read_text('utf-8'))
    data = json.loads(''.join(data_parser.parts)); original = copy.deepcopy(data)
    expected = copy.deepcopy(original)
    missing = missing_covers(expected)
    missing_ids = {row['book_id'] for row in missing}
    for book in expected['books']:
        if book['book_id'] in missing_ids: book['cover']=''
    if missing and 'collection_status' in expected:
        expected['collection_status']['complete']=False
        expected['collection_status']['message']='部分封面或材料暂未取得，年度报告仍可正常浏览和导出。'
        expected['verification_status']='partial_verified'
    build_html(data, target)
    if expected != data: raise ValueError('视觉重建意外改动了阅读数据')
    old_art = ReadingData('reading-art'); old_art.feed(source.read_text('utf-8'))
    new_art = ReadingData('reading-art'); new_art.feed(target.read_text('utf-8'))
    if json.loads(''.join(old_art.parts)) != json.loads(''.join(new_art.parts)):
        raise ValueError('原年鉴包含不同插画，停止更新；请显式提供原自定义素材后再重建')
    if args.screenshots:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(executable_path='C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe', headless=True)
            try:
                page = browser.new_page(reduced_motion='reduce')
                errors = []; page.on('pageerror', lambda e: errors.append(str(e)))
                page.goto(target.as_uri(), wait_until='load')
                page.evaluate('document.fonts.ready')
                for width in (1440,768,375):
                    page.set_viewport_size({'width':width,'height':1000})
                    assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
                    for selector, name in [('.distribution','distribution'),('.investment-section','investment')]:
                        page.locator(selector).screenshot(path=str(target.parent/f'{name}-{width}.png'))
                for ratio in ('3:4','1:1','4:5'):
                    for kind in ('distribution','stats'):
                        encoded = page.evaluate("""async ({ratio,kind})=>{
                            const data=JSON.parse(document.querySelector('#reading-data').textContent),art=JSON.parse(document.querySelector('#reading-art').textContent);
                            const loadImage=src=>new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=reject;im.src=src;});
                            return (await ReadingShareArtwork.create({data,art,loadImage}).render({id:kind,kind},ratio)).toDataURL();
                        }""", {'ratio':ratio,'kind':kind})
                        import base64
                        (target.parent/f'{kind}-share-{ratio.replace(":","-")}.png').write_bytes(base64.b64decode(encoded.split(',',1)[1]))
                assert not errors, errors
            finally:
                browser.close()
    if args.update_source:
        backup = target.parent/'previous-yearbook.html'
        if not backup.exists(): shutil.copy2(source, backup)
        shutil.copy2(target, source)
    print(json.dumps({'output':str(target),'data_unchanged':original==data,'reading_records_unchanged':True,'source_updated':args.update_source}, ensure_ascii=False))


if __name__ == '__main__': main()
