"""Cover validation with graceful fallback; strict completeness is opt-in."""
import base64
import io
import json
import re
from html.parser import HTMLParser


class MissingCovers(ValueError):
    def __init__(self, books):
        self.books = books
        super().__init__(f'有{len(books)}本书缺少真实封面或图片无效，请补齐后再生成正式年鉴。')


def image_data(content, label='书封'):
    if content.startswith(b'\x89PNG\r\n\x1a\n'): mime = 'image/png'
    elif content.startswith(b'\xff\xd8\xff'): mime = 'image/jpeg'
    elif content[:4] == b'RIFF' and content[8:12] == b'WEBP': mime = 'image/webp'
    else: raise ValueError('书封须为PNG/JPEG/WebP：'+label)
    if len(content) > 8*1024*1024: raise ValueError('单张书封不能超过8MB')
    try:
        from PIL import Image
    except ImportError:
        raise ValueError('缺少图片校验依赖Pillow，请按Skill安装说明补齐requirements.txt') from None
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.width<1 or image.height<1 or image.width*image.height>32_000_000:
                raise ValueError('图片尺寸超出安全范围')
            image.verify()
        with Image.open(io.BytesIO(content)) as image: image.load()
    except Exception as error:
        raise ValueError('图片无法完整解码：'+label) from error
    return 'data:'+mime+';base64,'+base64.b64encode(content).decode('ascii')


def valid_embedded_cover(value):
    if not isinstance(value,str) or len(value)>12*1024*1024: return False
    match = re.fullmatch(r'data:(image/(?:png|jpeg|webp));base64,([A-Za-z0-9+/=]+)',value)
    if not match: return False
    try:
        canonical = image_data(base64.b64decode(match[2],validate=True))
        return canonical == value
    except ValueError:
        return False


def missing_covers(data):
    if not isinstance(data,dict) or not isinstance(data.get('books'),list):
        raise ValueError('年鉴书目结构无效')
    missing = []
    for book in data['books']:
        if not isinstance(book,dict): raise ValueError('年鉴书目结构无效')
        if not valid_embedded_cover(book.get('cover')):
            missing.append({'book_id':book.get('book_id',''),'title':book.get('title',''),
                            'reason':'invalid' if book.get('cover') else 'missing'})
    return missing


class YearbookData(HTMLParser):
    def __init__(self):
        super().__init__(); self.active=False; self.found=False; self.parts=[]
    def handle_starttag(self,tag,attrs):
        if tag=='script' and dict(attrs).get('id')=='reading-data':
            self.active=True; self.found=True
    def handle_endtag(self,tag):
        if tag=='script': self.active=False
    def handle_data(self,data):
        if self.active: self.parts.append(data)


def check_yearbook_page(page):
    """Reject malformed report data, not usable reports with missing covers."""
    parser=YearbookData(); parser.feed(page)
    if not parser.found: raise ValueError('年鉴缺少可核查的书目数据')
    data=json.loads(''.join(parser.parts))
    if isinstance(data,dict) and data.get('source_mode')=='sample': return page
    missing=missing_covers(data)
    if not isinstance(data.get('summary'),dict) or not isinstance(data['summary'].get('monthly'),list):
        raise ValueError('年鉴统计结构无效')
    for book in data['books']:
        if (not isinstance(book.get('book_id'),str) or not isinstance(book.get('title'),str)
                or not isinstance(book.get('highlights'),list) or not isinstance(book.get('thoughts'),list)):
            raise ValueError('年鉴书目结构无效')
    if missing:
        missing_ids={row['book_id'] for row in missing}
        for book in data['books']:
            if book['book_id'] in missing_ids: book['cover']=''
        serialized=json.dumps(data,ensure_ascii=False,allow_nan=False).replace('<','\\u003c').replace('\u2028','\\u2028').replace('\u2029','\\u2029')
        page=page.replace(''.join(parser.parts),serialized,1)
    return page
