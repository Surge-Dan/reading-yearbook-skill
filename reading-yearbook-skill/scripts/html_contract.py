"""Small shared contracts for collection, persistence and HTML presentation."""
import json
import math
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit


def nonnegative(value):
    if isinstance(value, bool):
        return None
    try:
        n = float(value)
        return n if math.isfinite(n) and n >= 0 else None
    except (ValueError, TypeError):
        return None


def category_name(value):
    if isinstance(value, dict):
        value = value.get('title') or value.get('categoryTitle') or ''
    return value.strip() if isinstance(value, str) else ''


def reading_status(progress, started=None):
    if progress == 100:
        return 'finished'
    if (progress is not None and progress > 0) or started is True:
        return 'reading'
    return 'unstarted' if started is False else 'unknown'


def safe_link(value):
    value = value if isinstance(value, str) else ''
    return value if urlsplit(value).scheme in {'https', 'weread'} else ''


def atomic_text(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            stream.write(text)
        # Windows readers/indexers can briefly deny replacement of a closed
        # destination. Retry only this filesystem operation, never generation.
        for attempt in range(4):
            try:
                os.replace(name, path)
                break
            except PermissionError as error:
                if getattr(error, 'winerror', None) not in (5, 32, 33) or attempt == 3:
                    raise
                time.sleep((0.02, 0.05, 0.1)[attempt])
    finally:
        if os.path.exists(name):
            os.unlink(name)


def atomic_json(path, data):
    atomic_text(path, json.dumps(data, ensure_ascii=False, allow_nan=False, indent=2))


def valid_response(api, value):
    if not isinstance(value, dict) or value.get('errcode') not in (None, 0):
        return False
    field = {'/shelf/sync': 'books', '/user/notebooks': 'books', '/readdata/detail': 'readStat',
             '/book/bookmarklist': 'updated', '/review/list/mine': 'reviews'}.get(api)
    if field:
        return isinstance(value.get(field), list) and all(isinstance(r, dict) and
            (api!='/review/list/mine' or 'review' not in r or isinstance(r['review'],dict)) for r in value[field])
    if api == '/book/getprogress':
        return isinstance(value.get('book'), dict)
    if api == '/book/info':
        book = value.get('book') or value
        return isinstance(book, dict) and bool(book.get('title'))
    return True
