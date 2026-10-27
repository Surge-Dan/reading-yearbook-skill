import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests'))
from test_reading_html import fixture
sys.path.insert(0, str(ROOT / 'reading-yearbook-skill' / 'scripts'))
from build_reading_html import adapt_data, build_html

output = ROOT / 'demo-output' / 'ebook-ui-yearbook.html'
raw = fixture()
raw['books'][2]['intro'] = '<script>window.PWNED=1</script>' + '原始简介与适用范围。' * 80
build_html(adapt_data(raw), output)
page = output.read_text('utf-8')
assert 'href="#ebook"' in page, 'yearbook must link to ebook workbench'
assert 'data-reader-mode="readonly"' in page, 'yearbook must embed readonly reader'
assert 'id="ebookFile"' not in page, 'reader must not contain task controls'
assert page.count('id="ebook-app-mounted"') == 1, 'mount script must appear once'
assert 'window.ReadingShareArtwork' in page and 'function createDigest' in page
assert '__EBOOK_' not in page
print('PASS embedded ebook workbench: ' + str(output))
