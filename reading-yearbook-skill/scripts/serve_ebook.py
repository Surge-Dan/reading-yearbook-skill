"""Loopback-only ebook workbench. Credentials and source books never enter exports."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import secrets
import threading
import uuid
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor
from contextlib import nullcontext
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from html_contract import atomic_json, atomic_text

ROOT = Path(__file__).resolve().parents[1]
MAX_UPLOAD = 32 * 1024 * 1024
EXTENSIONS = {'.txt', '.md', '.epub', '.pdf'}
JOB_ID = re.compile(r'^[a-f0-9]{32}$')
ACTIVE = {'queued', 'running', 'awaiting_agent', 'awaiting_response', 'needs_book_confirmation'}
STATES = ACTIVE | {'needs_approval', 'completed', 'failed', 'cancelled', 'interrupted'}


def public_error(error):
    if isinstance(error, InterruptedError):
        return str(error)[:1000]
    if isinstance(error, OSError):
        return '本地文件读写失败，请让助手检查输出目录与 Skill 安装资源'
    message = str(error)[:1000]
    message = re.sub(r"(?:[A-Za-z]:[\\/]|\\\\)[^\n\"']+", '[本地路径]', message)
    message = re.sub(r"(?<![\w:])/(?:[^\s/]+/)+[^\s,;]*", '[本地路径]', message)
    return message


def valid_saved_job(job, expected_id):
    if not isinstance(job, dict) or job.get('id') != expected_id or job.get('state') not in STATES:
        return False
    if any(not isinstance(job.get(k), str) for k in ('filename', 'created_at', 'suffix', 'focus', 'stage', 'message')):
        return False
    if (job['suffix'] not in EXTENSIONS and not (job.get('input_mode') == 'title' and job['suffix'] == '')) or len(job['focus']) > 1000:
        return False
    if job.get('input_mode') == 'title' and (not isinstance(job.get('book_query'), dict) or
        any(not isinstance(job['book_query'].get(k), str) or len(job['book_query'][k]) > 200 for k in ('title','author'))):
        return False
    if any(type(job.get(k)) is not int or job[k] < 0 for k in ('completed', 'total')):
        return False
    if job['state'] == 'completed' and (not isinstance(job.get('analysis'), dict) or not isinstance(job.get('digest'), str)):
        return False
    return True


def safe_json(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')


def asset(name):
    path = ROOT / 'assets' / name
    return path.read_text('utf-8') if path.is_file() else ''


def workbench_page(config=None, result=None, yearbook=None, legacy=False):
    if not legacy:
        from report_reader import reader_page
        return reader_page(result, yearbook)
    section = asset('ebook-section.html') or '<main id="ebook"><h1>电子书精华</h1></main>'
    css = asset('ebook-app.css')
    if yearbook:
        page = Path(yearbook).read_text('utf-8')
        from cover_contract import check_yearbook_page
        try:
            page=check_yearbook_page(page)
        except (ValueError,TypeError) as error:
            notice='<section role="status" data-yearbook-blocked="true"><h2>年度报告暂未就绪</h2><p>年鉴书目数据无法读取，请让助手修复后重新打开；电子书蒸馏仍可使用。</p></section>'
            return workbench_page(config,result).replace('<main>','<main>'+notice,1)
        existing = re.search(r'<section\b[^>]*\bid="ebook"[^>]*>', page)
        if existing:
            depth = 0
            for tag in re.finditer(r'<(/?)section\b[^>]*>', page[existing.start():]):
                depth += -1 if tag.group(1) else 1
                if depth == 0:
                    page = page[:existing.start()] + section + page[existing.start()+tag.end():]
                    break
        else:
            page = page.replace('</main>', section + '</main>', 1)
        if 'id="ebook-app-mounted"' in page:
            page = re.sub(r'<script id="ebook-app-mounted">.*?</script>',
                          lambda _: '<script id="ebook-app-mounted">' + asset('ebook-app.js') + '</script>', page, flags=re.S)
        else:
            page = page.replace('</body>', '<script id="ebook-app-mounted">' + asset('ebook-app.js') + '</script></body>', 1)
        artwork = '<script>' + asset('reading-share-art.js') + '</script>'
        if '<script>/* Editorial share artwork.' in page:
            page = re.sub(r'<script>/\* Editorial share artwork\..*?</script>', lambda _: artwork, page, flags=re.S)
        else:
            page = page.replace('<script id="ebook-app-mounted">', artwork + '<script id="ebook-app-mounted">', 1)
        page = page.replace('</head>', '<style>' + css + '</style></head>', 1)
    else:
        page = ('<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">'
                '<meta name="viewport" content="width=device-width,initial-scale=1">'
                '<title>年年阅 · 电子书精华</title><style>' + asset('reading-app.css') + '\n' + asset('reading-art.css') + '\n' + css +
                '</style></head><body class="ebook-standalone"><div class="paper"><header class="masthead"><a href="#ebook">年年阅</a>'
                '<span>电子书精华</span></header><main>' + section + '</main></div>'
                '<script>' + asset('reading-share-art.js') + '</script>'
                '<script id="ebook-app-mounted">' + asset('ebook-app.js') + '</script></body></html>')
    # Configuration precedes deferred mounting; data is never executable HTML.
    injection = '<script id="ebook-config">window.EBOOK_CONFIG=' + safe_json(config or {}) + ';window.EBOOK_RESULT=' + safe_json(result) + ';</script>'
    return page.replace('</head>', injection + '</head>', 1)


def offline_page(analysis, digest):
    return workbench_page(result={'analysis': analysis, 'digest': digest})


class BusyError(ValueError):
    pass


class JobStore:
    def __init__(self, output, runner, pipeline=None):
        self.output = Path(output).resolve()
        self.jobs_dir = self.output / '.ebook-workbench' / 'jobs'
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.runner = runner
        self.pipeline = pipeline
        self.token = secrets.token_urlsafe(32)
        self.agent_token = secrets.token_urlsafe(32)
        self.agent_mode = runner.info().get('mode') == 'current-agent-instructed-tools'
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='ebook')
        self.jobs = {}
        self.events = {}
        self.runners = {}
        # The executor is serial: replacing a handle with a later queued future
        # still covers older work. Retain done handles until retry or recovery;
        # an old worker callback must never remove a replacement's handle.
        self.workers = {}
        for state_file in self.jobs_dir.glob('*/state.json'):
            if not JOB_ID.fullmatch(state_file.parent.name):
                continue
            try:
                job = json.loads(state_file.read_text('utf-8'))
                if not valid_saved_job(job, state_file.parent.name):
                    continue
                if job.get('state') in ACTIVE:
                    job.update(state='interrupted', message='上次服务已停止，可重试并复用已完成阶段')
                self.jobs[job['id']] = job
                self._save(job)
            except (ValueError, OSError, TypeError):
                continue

    def _save(self, job):
        atomic_json(self.jobs_dir / job['id'] / 'state.json', job)

    def _job(self, job_id):
        if not JOB_ID.fullmatch(job_id) or job_id not in self.jobs:
            raise KeyError('任务不存在')
        return self.jobs[job_id]

    def get(self, job_id):
        with self.lock:
            return json.loads(json.dumps(self._job(job_id), ensure_ascii=False))

    def state(self):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j['created_at'], reverse=True)[:30]
            return {'runner': self.runner.info(), 'jobs': json.loads(json.dumps(jobs, ensure_ascii=False))}

    def _check_busy(self):
        if any(j['state'] in ACTIVE for j in self.jobs.values()):
            raise BusyError('当前正在蒸馏一本书，请等待完成或先取消')

    def create(self, filename, content, focus='', assistant_session=None):
        suffix = Path(filename).suffix.lower()
        if suffix not in EXTENSIONS:
            raise ValueError('支持 EPUB、PDF、TXT 和 MD 文件')
        if not content:
            raise ValueError('文件为空，请选择有正文的电子书')
        if len(content) > MAX_UPLOAD:
            raise ValueError('文件超过 32 MB，请使用文本版或拆分为明确的处理范围')
        if not self.runner.info().get('available'):
            raise ValueError('AI 尚未连接，请让启动 Skill 的助手检查 Codex 或 Claude 登录')
        if len(focus) > 1000:
            raise ValueError('应用方向最多 1000 字')
        with self.lock:
            self._check_busy()
            job_id = uuid.uuid4().hex
            job_dir = self.jobs_dir / job_id
            job_dir.mkdir()
            (job_dir / ('source' + suffix)).write_bytes(content)
            name = filename.replace('\\', '/').rsplit('/', 1)[-1][:200]
            job = {'id': job_id, 'filename': name, 'suffix': suffix, 'focus': focus,
                   'runner_mode': self.runner.info().get('mode','legacy-cli'),
                   'created_at': datetime.now(timezone.utc).isoformat(),
                   'state': 'queued', 'stage': 'queued', 'message': '正在准备正文',
                   'completed': 0, 'total': 0, 'error': None}
            if assistant_session is not None:
                job.update(assistant_session=assistant_session,assistant_input=True)
            self.jobs[job_id] = job
            self._start(job)
            return self.get(job_id)

    def create_title(self, title, author='', focus=''):
        from ebook_title import text
        title = text(title, '书名', 200)
        if not isinstance(author, str) or len(author) > 200 or not isinstance(focus, str) or len(focus) > 1000:
            raise ValueError('作者或应用问题过长')
        if not self.agent_mode or not self.runner.info().get('available'):
            raise ValueError('书名模式需要当前助手，请让助手以 agent 模式启动工作台')
        with self.lock:
            self._check_busy()
            job_id = uuid.uuid4().hex
            (self.jobs_dir / job_id).mkdir()
            job = {'id':job_id,'input_mode':'title','book_query':{'title':title,'author':author.strip()},
                   'filename':title,'suffix':'','focus':focus.strip(),
                   'runner_mode':'current-agent-instructed-tools','created_at':datetime.now(timezone.utc).isoformat(),
                   'state':'queued','stage':'queued','message':'准备确认书籍','completed':0,'total':0,'error':None}
            self.jobs[job_id] = job
            self._start(job)
            return self.get(job_id)

    def _start(self, job, allow_large=False):
        event = threading.Event()
        self.events[job['id']] = event
        job.pop('diagnostic', None)
        job.update(state='queued', error=None, message='准备继续处理', allow_large=allow_large)
        if not self.agent_mode and job.get('runner_mode') == 'current-agent-instructed-tools':
            job.update(state='interrupted', message='此任务属于当前 Agent 模式，请启动原模式继续')
            self._save(job)
            return
        if self.agent_mode:
            if job.get('runner_mode') != 'current-agent-instructed-tools':
                job.update(state='interrupted', message='历史任务使用自动 CLI 模式，请显式启动原模式继续')
                self._save(job)
                return
            if job.get('input_mode') == 'title':
                job.update(state='awaiting_agent', stage='handoff', message='书名已接收。请回同一助手对话说“开始蒸馏”。')
                self._save(job)
                return
            if job.get('assistant_input'):
                job.update(stage='prepare',message='正文已接收，正在准备来源')
                self._save(job)
                self.workers[job['id']] = self.executor.submit(self._prepare_agent_source,job['id'],event)
                return
            self._prepare_agent_source(job['id'],event)
            return
        self._save(job)
        self.workers[job['id']] = self.executor.submit(self._run, job['id'], event, allow_large)

    def _prepare_agent_source(self,job_id,event):
        """Prepare assistant uploads off the HTTP thread; return a job ID immediately."""
        with self.lock:
            if event.is_set() or self.events.get(job_id) is not event:return
            job=self.jobs[job_id]
        try:
            from ebook_document import parse_document
            document=parse_document(self.jobs_dir/job_id/('source'+job['suffix']))
            error=None
        except Exception as failure:
            document=None;error=public_error(failure)
        with self.lock:
            if event.is_set() or self.events.get(job_id) is not event:return
            if not error:
                try:
                    atomic_json(self.jobs_dir/job_id/'parsed-source.json',document)
                except Exception as failure:
                    error=public_error(failure)
            if error:
                job.update(state='failed',error=error,message='正文未能解析，请检查文件')
            else:
                job.update(state='awaiting_agent',stage='handoff',message='正文已准备好，等待当前助手领取')
            self._save(job)

    def agent_action(self, job_id, action, data):
        if not self.agent_mode or not isinstance(data, dict):
            raise ValueError('当前工作台不是当前 Agent 模式')
        if action == 'recover':
            return self._recover_session(job_id, data)
        with self.lock:
            job = self._job(job_id)
            owner=job.get('assistant_session')
            bound=self.runners.get(job_id)
            if owner is None and bound: owner=bound.identity['session']
            if owner is not None and data.get('session')!=owner: raise ValueError('任务由另一个对话持有')
            if action in ('select-book','cancel','retry','approve'):
                if not owner: raise ValueError('请先由当前助手领取任务')
                if action=='select-book': return {'job':self.select_book(job_id,data.get('book_id'),data.get('selection_id'))}
                return {'job':self.action(job_id,action)}
            if action == 'claim':
                if job.get('runner_mode') != 'current-agent-instructed-tools':
                    raise ValueError('历史 CLI 任务不能由当前 Agent 领取')
                if job['state'] != 'awaiting_agent':
                    raise ValueError('任务不可领取，请检查状态；中断任务需重试')
                event = self.events[job_id]
                def notify(update):
                    with self.lock:
                        if not event.is_set():
                            job.update(update)
                            self._save(job)
                ownership_path = self.jobs_dir / job_id / '.agent' / 'ownership.json'
                previous_ownership = json.loads(ownership_path.read_text('utf-8')) if ownership_path.exists() else {}
                runner = self.runner.bind(self.jobs_dir / job_id, job_id, data, notify, event)
                ownership = dict(previous_ownership, execution_identity=dict(runner.identity), attempt_id=runner.attempt)
                claimed = dict(job, assistant_session=data['session'], state='queued', message='当前 Agent 已领取，正在准备正文')
                audit_saved = False
                try:
                    atomic_json(ownership_path, ownership)
                    audit_saved = True
                    self._save(claimed)
                except Exception:
                    runner.revoke('领取未能保存，尝试已失效')
                    if audit_saved:
                        atomic_json(ownership_path, previous_ownership)
                    raise
                job.update(claimed)
                self.runners[job_id] = runner
                self.workers[job_id] = self.executor.submit(self._run, job_id, event, job.get('allow_large', False), runner)
                return {'job': self.get(job_id), 'attempt_id': runner.attempt}
            runner = self.runners.get(job_id)
            event = self.events.get(job_id)
            if not runner or not event or event.is_set():
                raise ValueError('任务已停止或领取已失效')
        # Runner callbacks take the store lock: do not hold it across runner calls.
        if action == 'next':
            job = self.get(job_id)
            if job['state'] not in ACTIVE:
                return {'job': job, 'request': None}
            request = runner.next(data.get('session'))
            if request:
                request = {k: request[k] for k in ('request_id', 'attempt_id', 'stage', 'sequence', 'input_digest')}
                request.update(request_path=str(runner.directory / 'request.json'), job_dir=str(self.jobs_dir / job_id))
            return {'job': self.get(job_id), 'request': request}
        if action == 'submit':
            return {'status': runner.submit(data.get('session'), data.get('request_id'), data.get('answer'))}
        if action == 'release':
            runner.next(data.get('session'))  # Verify owner before revoking.
            runner.revoke('当前 Agent 已释放任务，请重试')
            with self.lock:
                if self.runners.get(job_id) is not runner or self.events.get(job_id) is not event or job['state']=='completed':
                    raise ValueError('旧尝试已结束，释放操作未影响当前任务')
                event.set()
                job.update(state='interrupted', message='当前 Agent 已释放任务，请重试')
                self._save(job)
            return {'status': 'released'}
        raise ValueError('不支持的 Agent 操作')

    def _recover_session(self, job_id, data):
        """Explicit owner CAS for a stopped attempt; never retries or approves work."""
        session, expected = data.get('session'), data.get('expected_session')
        if (data.get('confirm_transfer') is not True or
            any(not isinstance(value, str) or not value.strip() or len(value) > 200
                for value in (session, expected)) or session == expected):
            raise ValueError('恢复需要新 session、原 session 和明确确认转移')

        def stopped_job():
            job = self._job(job_id)
            if job.get('runner_mode') != 'current-agent-instructed-tools':
                raise ValueError('历史 CLI 任务不能转移给当前 Agent')
            if job.get('assistant_session') != expected:
                raise ValueError('原对话身份已变化，请重新核对任务')
            if job['state'] not in {'interrupted', 'failed', 'cancelled'}:
                raise ValueError('仅可恢复已停止的任务')
            worker = self.workers.get(job_id)
            if worker is not None and not worker.done():
                raise ValueError('上一尝试仍在停止，请等待结束后恢复')
            return job

        with self.lock:
            stopped_job()
            runner = self.runners.get(job_id)
        # Match runner callbacks' lock order. Recheck the snapshot after acquiring
        # both locks: a concurrent retry/recovery must never retire a new attempt.
        with runner.condition if runner else nullcontext():
            with self.lock:
                job = stopped_job()
                if self.runners.get(job_id) is not runner:
                    raise ValueError('任务尝试已变化，请重新核对后恢复')
                event = self.events.get(job_id)
                if (runner and not runner.revoked and
                    not (runner.cancel_event and runner.cancel_event.is_set()) and runner.clock() < runner.deadline):
                    raise ValueError('上一尝试仍持有有效领取，不能转移')
                ownership_path = self.jobs_dir / job_id / '.agent' / 'ownership.json'
                previous_ownership = json.loads(ownership_path.read_text('utf-8')) if ownership_path.exists() else {}
                previous = dict(runner.identity) if runner else dict(previous_ownership.get('execution_identity') or {'session': expected})
                transfer = {'previous_session': expected, 'new_session': session,
                            'execution_identity': previous,
                            'attempt_id': runner.attempt if runner else previous_ownership.get('attempt_id'),
                            'transferred_at': datetime.now(timezone.utc).isoformat()}
                ownership = dict(previous_ownership, session_transfers=[*previous_ownership.get('session_transfers', []), transfer])
                atomic_json(ownership_path, ownership)
                transferred = dict(job, assistant_session=session, message='新对话已接管停止的任务；授权后重试并重新领取')
                try:
                    self._save(transferred)
                except Exception:
                    atomic_json(ownership_path, previous_ownership)
                    raise
                if event:
                    event.set()
                if runner:
                    runner.revoke('任务已由新对话显式恢复，旧尝试已失效')
                self.runners.pop(job_id, None)
                self.events.pop(job_id, None)
                self.workers.pop(job_id, None)
                job.update(transferred)
                return {'job': self.get(job_id)}

    def _run(self, job_id, event, allow_large, runner=None):
        def progress(update):
            with self.lock:
                if not event.is_set() and self.events.get(job_id) is event:
                    fields = {k: update[k] for k in ('stage', 'message', 'completed', 'total', 'estimate') if k in update}
                    self.jobs[job_id].update(fields)
                    self._save(self.jobs[job_id])

        with self.lock:
            job = self.jobs[job_id]
            if event.is_set() or self.events.get(job_id) is not event:
                return
            job['state'] = 'running'
            self._save(job)
        job_dir = self.jobs_dir / job_id
        deep = job_dir / 'deep'
        try:
            pipeline = self.pipeline
            if job.get('input_mode') == 'title':
                from ebook_title import distill_title
                def choose(books):
                    with self.lock:
                        if event.is_set() or self.events.get(job_id) is not event: raise InterruptedError('已取消')
                        job.update(state='needs_book_confirmation',book_candidates=books,selection_id=uuid.uuid4().hex,
                                   selected_book=None,message='有同名书，请在助手对话中选择作者或版本后继续')
                        self._save(job)
                    while True:
                        if event.is_set(): raise InterruptedError('已取消')
                        runner.check()
                        with self.lock:
                            selected = job.get('selected_book')
                            if selected: return next(b for b in books if b['id'] == selected)
                        time.sleep(.05)
                result = distill_title(job['book_query'], deep, runner, progress=progress,
                                       cancel_event=event, focus=job['focus'], choose=choose)
            else:
                if pipeline is None:
                    from ebook_pipeline import distill
                    pipeline = distill
                result = pipeline(job_dir / ('source' + job['suffix']), deep, runner or self.runner,
                                  progress=progress, cancel_event=event, focus=job['focus'], allow_large=allow_large,
                                  **({'source_name':job['filename']} if self.pipeline is None else {}))
            if event.is_set():
                raise InterruptedError('已取消')
            if runner: runner.check()
            digest = (deep / 'DIGEST.md').read_text('utf-8')
            page = offline_page(result, digest)
            with self.lock:
                if event.is_set() or self.events.get(job_id) is not event:
                    raise InterruptedError('已取消')
                if runner: runner.check()
                atomic_text(deep / 'index.html', page)
                job.update(state='completed', stage='complete', message='精华已生成，请查看来源与核验状态',
                           analysis=result, digest=digest, result_url=f'/results/{job_id}.html', error=None)
        except InterruptedError as error:
            with self.lock:
                if self.events.get(job_id) is event:
                    job.update(state='cancelled' if event.is_set() and job['state']!='interrupted' else 'interrupted', message=public_error(error), error=None)
        except Exception as error:
            with self.lock:
                if self.events.get(job_id) is not event:
                    pass
                elif event.is_set():
                    job.update(state='cancelled', message='已取消，可重试继续', error=None)
                elif hasattr(error, 'estimate'):
                    job.update(state='needs_approval', stage='budget', message=str(error), estimate=error.estimate)
                else:
                    job.update(state='failed', message='本次蒸馏未完成，可检查提示后重试', error=public_error(error))
                    if hasattr(error, 'diagnostic'):
                        job['diagnostic'] = error.diagnostic
        finally:
            if runner:
                runner.revoke('本轮任务已结束，请检查任务状态')
            with self.lock:
                if self.events.get(job_id) is event:
                    if job['state']!='completed':
                        from ebook_pipeline import _archive_generation
                        _archive_generation(deep)
                    self._save(job)

    def select_book(self, job_id, selected, selection_id=None):
        if not isinstance(selected, str): raise ValueError('书籍选择必须为候选 ID')
        with self.lock:
            job = self._job(job_id)
            if job['state'] != 'needs_book_confirmation' or selection_id != job.get('selection_id'):
                raise ValueError('书籍选择已失效，请刷新任务')
            runner = self.runners.get(job_id)
            if not runner or self.events[job_id].is_set(): raise ValueError('任务已停止')
            if selected not in {b['id'] for b in job.get('book_candidates', [])}: raise ValueError('书籍不在候选列表中')
            # Do not acquire the runner lock under the store lock (callbacks invert that order).
            job.update(selected_book=selected,state='running',message='书籍已选择，继续收集公开资料')
            self._save(job)
            return self.get(job_id)

    def action(self, job_id, action):
        with self.lock:
            job = self._job(job_id)
            if action == 'cancel':
                if job['state'] in ACTIVE:
                    self.events[job_id].set()
                    if job['state'] in {'queued', 'awaiting_agent', 'awaiting_response'}:
                        job.update(state='cancelled', message='已取消；请同时停止对话中的分析。可重试继续')
                    else:
                        job['message'] = '正在停止当前阶段…'
                elif job['state'] == 'needs_approval':
                    job.update(state='cancelled', message='已取消')
                else:
                    raise ValueError('该任务已停止')
                self._save(job)
            elif action in {'retry', 'approve'}:
                allowed = {'needs_approval'} if action == 'approve' else {'failed', 'cancelled', 'interrupted'}
                if job['state'] not in allowed:
                    raise ValueError('当前任务状态不支持此操作')
                self._check_busy()
                self._start(job, action == 'approve' or job.get('allow_large', False))
            else:
                raise ValueError('不支持的操作')
            return self.get(job_id)

    def close(self):
        with self.lock:
            for event in self.events.values():
                event.set()
        self.executor.shutdown(wait=True, cancel_futures=True)


def create_server(store, port=0, yearbook=None, legacy_workbench=False):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            # Do not log source names, request URLs, tokens, or model payloads.
            pass

        def send(self, status, body, content_type='application/json; charset=utf-8'):
            if not isinstance(body, bytes):
                body = (safe_json(body) if 'json' in content_type else body).encode('utf-8')
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; font-src data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def authorize(self, api=False, mutation=False, agent=False):
            expected_host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != expected_host:
                self.send(403, {'error': '只允许本机工作台访问'})
                return False
            header = 'X-Ebook-Agent-Token' if agent else 'X-Ebook-Token'
            token = store.agent_token if agent else store.token
            if api and not hmac.compare_digest(self.headers.get(header, '').encode('utf-8'), token.encode('ascii')):
                self.send(403, {'error': '连接已过期，请重新打开工作台'})
                return False
            if mutation and self.headers.get('Origin') != 'http://' + expected_host:
                self.send(403, {'error': '请从年年阅工作台上传文件'})
                return False
            return True

        def do_GET(self):
            path = urlsplit(self.path).path
            if not self.authorize(path.startswith('/api/')):
                return
            try:
                if path == '/':
                    self.send(200, workbench_page({'apiBase': '', 'token': store.token, 'output': str(store.output)}, yearbook=yearbook, legacy=legacy_workbench), 'text/html; charset=utf-8')
                elif path == '/api/state':
                    self.send(200, store.state())
                elif path.startswith('/api/jobs/'):
                    self.send(200, {'job': store.get(path.removeprefix('/api/jobs/'))})
                elif path.startswith('/results/') and path.endswith('.html'):
                    job_id = path.removeprefix('/results/').removesuffix('.html')
                    job = store.get(job_id)
                    if job['state'] != 'completed':
                        raise KeyError('精华尚未生成')
                    self.send(200, offline_page(job['analysis'], job['digest']), 'text/html; charset=utf-8')
                else:
                    self.send(404, {'error': '页面不存在'})
            except KeyError as error:
                self.send(404, {'error': str(error).strip("'")})

        def do_POST(self):
            parsed = urlsplit(self.path)
            if not self.authorize(api=True, mutation=True, agent=parsed.path.startswith('/api/agent/')):
                return
            try:
                length = int(self.headers.get('Content-Length', '-1'))
                if length < 0 or length > MAX_UPLOAD:
                    self.send(413, {'error': '文件超过 32 MB 或请求长度无效'})
                    return
                self.connection.settimeout(30)
                body = self.rfile.read(length)
                if len(body) != length:
                    raise ValueError('文件上传不完整，请重新选择文件')
                if parsed.path.startswith('/api/agent/'):
                    from ebook_agent import strict_json
                    data = strict_json(body.decode('utf-8'))
                    if parsed.path == '/api/agent/list':
                        self.send(200, store.state())
                    elif parsed.path in ('/api/agent/create-title','/api/agent/create-file'):
                        if not store.agent_mode: raise ValueError('助手入口需要当前 Agent 模式')
                        session=data.get('session')
                        if not isinstance(session,str) or not session.strip() or len(session)>200: raise ValueError('需要当前助手 session')
                        with store.lock:
                            if parsed.path.endswith('create-title'):
                                job=store.create_title(data.get('title'),data.get('author',''),data.get('focus',''))
                            else:
                                from ebook_agent import local_source
                                filename,content=local_source(data.get('path'))
                                job=store.create(filename,content,data.get('focus',''),assistant_session=session)
                            store.jobs[job['id']]['assistant_session']=session
                            store._save(store.jobs[job['id']])
                        self.send(202,{'job':store.get(job['id'])})
                    else:
                        match = re.fullmatch(r'/api/agent/([a-f0-9]{32})/(claim|next|submit|release|select-book|cancel|retry|approve|recover)', parsed.path)
                        if not match:
                            self.send(404, {'error': '操作不存在'})
                            return
                        self.send(200, store.agent_action(*match.groups(), data))
                elif parsed.path == '/api/jobs':
                    query = parse_qs(parsed.query)
                    filename = query.get('name', [''])[0]
                    job = store.create(filename, body, query.get('focus', [''])[0])
                    self.send(202, {'job': job})
                elif parsed.path == '/api/title-jobs':
                    if len(body) > 8192: raise ValueError('书名请求过大')
                    from ebook_agent import strict_json
                    data = strict_json(body.decode('utf-8'))
                    self.send(202, {'job':store.create_title(data.get('title'), data.get('author',''), data.get('focus',''))})
                elif re.fullmatch(r'/api/jobs/[a-f0-9]{32}/select-book', parsed.path):
                    if len(body) > 1024: raise ValueError('书籍选择请求过大')
                    from ebook_agent import strict_json
                    data = strict_json(body.decode('utf-8'))
                    self.send(202, {'job':store.select_book(parsed.path.split('/')[3],data.get('book_id'),data.get('selection_id'))})
                else:
                    match = re.fullmatch(r'/api/jobs/([a-f0-9]{32})/(cancel|retry|approve)', parsed.path)
                    if not match:
                        self.send(404, {'error': '操作不存在'})
                        return
                    self.send(202, {'job': store.action(*match.groups())})
            except BusyError as error:
                self.send(409, {'error': str(error)})
            except InterruptedError as error:
                self.send(409, {'error': public_error(error)})
            except (ValueError, OSError) as error:
                self.send(400, {'error': public_error(error)})
            except KeyError:
                self.send(404, {'error': '任务不存在'})

    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    if store.agent_mode:
        atomic_json(store.output / '.ebook-workbench/agent-runtime.json', {
            'url': f'http://127.0.0.1:{server.server_port}', 'token': store.agent_token})
    return server


def main():
    parser = argparse.ArgumentParser(description='由助手启动年年阅电子书工作台')
    parser.add_argument('--output', type=Path, default=Path('output/books'))
    parser.add_argument('--runner', choices=['agent', 'auto', 'codex', 'claude'], default='agent')
    parser.add_argument('--stage-timeout', type=int, default=180, help='每个模型阶段的等待上限，30–900 秒；不自动重试')
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--yearbook', type=Path)
    parser.add_argument('--legacy-workbench', action='store_true', help='显式启用旧开发工作台，默认只读报告')
    parser.add_argument('--open', action='store_true')
    args = parser.parse_args()
    from ebook_runner import create_runner
    store = JobStore(args.output, create_runner(args.runner, timeout=args.stage_timeout))
    server = create_server(store, args.port, args.yearbook, args.legacy_workbench)
    url = f'http://127.0.0.1:{server.server_port}/'
    atomic_json(store.output / '.ebook-workbench/runtime.json', {'pid': os.getpid(), 'url': url})
    print(safe_json({'url': url, 'pid': os.getpid(), 'runner': store.runner.info()}), flush=True)
    if args.open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        store.close()


if __name__ == '__main__':
    main()
