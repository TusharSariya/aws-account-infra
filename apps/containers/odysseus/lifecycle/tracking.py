"""Reference-count admitted work across streaming responses and detached tasks."""
import asyncio
from contextvars import ContextVar, copy_context
from functools import wraps
import json
import threading
import time
import urllib.request
import uuid

CURRENT = ContextVar('homelab_admitted_work', default=None)


class AdmissionClosed(RuntimeError):
    pass


class Tracker:
    def __init__(self, endpoint, token, pod, transport=None):
        self.endpoint, self.token, self.pod = endpoint, token, pod
        self.lock = threading.RLock()
        self.tickets = {}
        self.transport = transport or self.request
        self.known = True

    def request(self, operation, payload):
        request = urllib.request.Request(self.endpoint + '/activity/odysseus/' + operation,
            data=json.dumps({**payload, 'pod_uid': self.pod}).encode(),
            headers={'Authorization': 'Bearer ' + self.token, 'Content-Type': 'application/json'}, method='POST')
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None
        with urllib.request.build_opener(NoRedirect).open(request, timeout=5) as response:
            if response.status != 200:
                raise AdmissionClosed('Lifecycle admission unavailable')
            return json.load(response)

    def begin(self):
        ticket = uuid.uuid4().hex
        with self.lock:
            if len(self.tickets) >= 128:
                raise AdmissionClosed('Activity tracking is full')
            # Retain an ambiguous begin until finish is acknowledged. The
            # controller's deadline/tombstone prevents a delayed resurrection.
            self.tickets[ticket] = 1
            try:
                self.transport('begin', {'ticket': ticket, 'parent': None, 'deadline': time.time() + 25})
            except Exception:
                self.tickets[ticket] = 0
                raise AdmissionClosed('New workspace work is not admitted') from None
        return Work(self, ticket)

    def join(self, ticket):
        self.retain(ticket)
        return Work(self, ticket)

    def retain(self, ticket):
        with self.lock:
            if ticket not in self.tickets or self.tickets[ticket] < 1:
                raise AdmissionClosed('Admitted work already ended')
            self.tickets[ticket] += 1

    def release(self, ticket):
        with self.lock:
            if ticket not in self.tickets or self.tickets[ticket] < 1:
                self.known = False
                return
            self.tickets[ticket] -= 1

    def report(self):
        with self.lock:
            for ticket, references in list(self.tickets.items()):
                if references == 0:
                    try:
                        self.transport('finish', {'ticket': ticket})
                    except Exception:
                        continue
                    del self.tickets[ticket]
            return self.transport('heartbeat', {'tickets': list(self.tickets), 'known': self.known})


class Work:
    def __init__(self, tracker, ticket):
        self.tracker, self.ticket = tracker, ticket

    def retain(self):
        self.tracker.retain(self.ticket)

    def release(self):
        self.tracker.release(self.ticket)


def task_factory(loop, coroutine, **kwargs):
    context = kwargs.get('context')
    work = context.get(CURRENT) if context is not None else CURRENT.get()
    code = getattr(coroutine, 'cr_code', None)
    # This pinned timer only evicts already-completed SSE replay buffers.
    passive = code and code.co_name == '_evict' and code.co_filename.endswith('/src/agent_runs.py')
    if work and not passive:
        work.retain()  # Before scheduling, including cancellation before first execution.
    try:
        task = asyncio.Task(coroutine, loop=loop, **kwargs)
    except BaseException:
        if work and not passive:
            work.release()
        raise
    if work and not passive:
        task.add_done_callback(lambda _: work.release())
    return task


async def admit(tracker):
    pending = asyncio.create_task(asyncio.to_thread(tracker.begin))
    try:
        return await asyncio.shield(pending)
    except asyncio.CancelledError:
        # Admission can be committed after the client disconnects. Retire that
        # result instead of leaving an acknowledged root with no owner.
        def retire(future):
            if not future.cancelled() and future.exception() is None:
                future.result().release()
        pending.add_done_callback(retire)
        raise


def scheduled(tracker):
    """Every scheduled execution needs new admission, even from a UI request."""
    def decorate(function):
        @wraps(function)
        async def run(*args, **kwargs):
            work = await admit(tracker)
            token = CURRENT.set(work)
            try:
                return await function(*args, **kwargs)
            finally:
                CURRENT.reset(token)
                work.release()
        return run
    return decorate


def install_thread_hooks():
    """Track submitted work, excluding idle ThreadPoolExecutor worker lifetimes."""
    from concurrent.futures import ThreadPoolExecutor
    original_submit = ThreadPoolExecutor.submit
    original_start = threading.Thread.start

    def submit(executor, function, /, *args, **kwargs):
        work, context = CURRENT.get(), copy_context()
        if not work:
            return original_submit(executor, function, *args, **kwargs)
        work.retain()
        try:
            future = original_submit(executor, context.run, function, *args, **kwargs)
        except BaseException:
            work.release()
            raise
        future.add_done_callback(lambda _: work.release())
        return future

    def start(thread):
        work, context = CURRENT.get(), copy_context()
        target = getattr(thread, '_target', None)
        pool_worker = getattr(target, '__module__', '') == 'concurrent.futures.thread'
        if not work or pool_worker:
            return original_start(thread)
        work.retain()
        original_run = thread.run
        def run():
            try:
                return context.run(original_run)
            finally:
                work.release()
        thread.run = run
        try:
            return original_start(thread)
        except BaseException:
            work.release()
            raise

    ThreadPoolExecutor.submit = submit
    threading.Thread.start = start
    return original_submit, original_start
