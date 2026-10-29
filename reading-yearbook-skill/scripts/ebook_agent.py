"""Local handoff client. No provider API, model subprocess or source instructions."""
import argparse
import json
import stat
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('JSON 字段重复：' + key)
            result[key] = value
        return result
    def invalid(value):
        raise ValueError('非有限 JSON 值：' + value)
    value = json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('必须为 JSON 对象')
    return value


def local_json(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    if not path.resolve().is_relative_to(root.resolve()):
        raise ValueError('文件必须位于当前任务目录')
    # Reject symlinks and Windows junctions, including ancestor escapes.
    for ancestor in (path, *path.parents):
        info = ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('不接受符号链接或重解析路径')
    if path.suffix.lower() != '.json' or not path.is_file() or path.stat().st_size > 32 * 1024 * 1024:
        raise ValueError('需要不超过 32 MB 的 JSON 文件')
    return strict_json(path.read_text('utf-8'))


def local_source(path):
    """Assistant-only local input; reject redirects before opening any bytes."""
    if not isinstance(path,str) or not Path(path).is_absolute(): raise ValueError('需要电子书绝对路径')
    source=Path(path)
    if source.drive.startswith('\\\\') or str(source).startswith('\\\\'): raise ValueError('仅支持本机普通文件路径')
    for ancestor in (source,*source.parents):
        info=ancestor.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info,'st_file_attributes',0)&0x400:
            raise ValueError('不接受符号链接或重解析路径')
    if source.suffix.lower() not in ('.epub','.pdf','.txt','.md') or not source.is_file() or not 0<source.stat().st_size<=32*1024*1024:
        raise ValueError('需要不超过 32 MB 的 EPUB/PDF/TXT/MD 正文')
    with source.open('rb') as handle: content=handle.read(32*1024*1024+1)
    if not content or len(content)>32*1024*1024: raise ValueError('文件为空或超过 32 MB')
    return source.name,content


class Client:
    def __init__(self, output):
        self.output = Path(output).absolute()
        runtime = local_json(self.output / '.ebook-workbench/agent-runtime.json', self.output)
        parsed = urlsplit(runtime['url'])
        if parsed.scheme != 'http' or parsed.hostname != '127.0.0.1' or not parsed.port or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ValueError('仅允许本机工作台 URL')
        self.origin = runtime['url']
        self.token = runtime['token']

    def call(self, action, data=None, job=None):
        if job is not None:
            import re
            if not re.fullmatch('[a-f0-9]{32}', job):
                raise ValueError('任务 ID 无效')
        url = self.origin + '/api/agent/' + ((job + '/') if job else '') + action
        request = urllib.request.Request(url, data=json.dumps(data or {}, allow_nan=False).encode(),
            headers={'Origin': self.origin, 'X-Ebook-Agent-Token': self.token, 'Content-Type': 'application/json'})
        # Do not inherit proxies or follow redirects away from loopback.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args):
                return None
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
        try:
            with opener.open(request, timeout=10) as response:
                return strict_json(response.read(32 * 1024 * 1024).decode('utf-8'))
        except urllib.error.HTTPError as error:
            raise ValueError(strict_json(error.read().decode('utf-8')).get('error', '本地请求失败')) from None

    def next(self, job, session):
        result = self.call('next', {'session': session}, job)
        pending = result.get('request')
        if pending:
            root = self.output / '.ebook-workbench/jobs' / job
            request = local_json(pending['request_path'], root)
            if any(request.get(k) != pending.get(k) for k in ('request_id', 'attempt_id', 'input_digest')) or request.get('job_id') != job:
                raise ValueError('请求绑定不匹配')
            from ebook_agent_bridge import digest
            if request['input_digest'] != digest({'prompt': request['prompt'], 'schema': request['schema']}):
                raise ValueError('请求内容摘要不匹配')
            result['request'] = request
        return result


def main():
    parser = argparse.ArgumentParser(description='年年阅当前 Agent 阶段交接')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('action', choices=['list', 'create-title', 'create-file', 'select-book', 'cancel', 'retry', 'approve', 'claim', 'next', 'submit', 'release', 'recover'])
    parser.add_argument('--job')
    parser.add_argument('--session')
    parser.add_argument('--expected-session')
    parser.add_argument('--confirm-transfer', action='store_true')
    parser.add_argument('--host')
    parser.add_argument('--model', default='unknown')
    parser.add_argument('--request-id')
    parser.add_argument('--reply', type=Path)
    parser.add_argument('--path', type=Path)
    parser.add_argument('--title')
    parser.add_argument('--author', default='')
    parser.add_argument('--focus', default='')
    parser.add_argument('--book-id')
    parser.add_argument('--selection-id')
    args = parser.parse_args()
    try:
        client = Client(args.output)
        if args.action == 'list':
            result = client.call('list')
        elif args.action in ('create-title','create-file'):
            if not args.session: raise ValueError('需要 --session')
            data={'session':args.session,'focus':args.focus}
            if args.action=='create-title':data.update(title=args.title,author=args.author)
            else:
                if not args.path:raise ValueError('需要 --path')
                data['path']=str(args.path.absolute())
            result=client.call(args.action,data)
        else:
            if not args.job or not args.session:
                raise ValueError('需要 --job 和 --session')
            data = {'session': args.session}
            if args.action == 'recover':
                if not args.expected_session or not args.confirm_transfer:
                    raise ValueError('恢复需要 --expected-session 和 --confirm-transfer')
                data.update(expected_session=args.expected_session, confirm_transfer=True)
            if args.action=='select-book':data.update(book_id=args.book_id,selection_id=args.selection_id)
            if args.action == 'claim':
                data.update(host=args.host, model=args.model)
            if args.action == 'submit':
                if not args.reply or not args.request_id:
                    raise ValueError('提交需要 --reply 和 --request-id')
                data.update(request_id=args.request_id, answer=local_json(args.reply,
                    args.output / '.ebook-workbench/jobs' / args.job))
            result = client.next(args.job, args.session) if args.action == 'next' else client.call(args.action, data, args.job)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    except (ValueError, OSError, KeyError) as error:
        parser.exit(1, '交接失败：' + str(error) + '\n')


if __name__ == '__main__':
    main()
