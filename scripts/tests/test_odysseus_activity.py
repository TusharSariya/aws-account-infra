import asyncio
from pathlib import Path
import sys
import unittest
import threading

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/containers/odysseus'))
from lifecycle.tracking import Tracker, CURRENT, task_factory, AdmissionClosed, scheduled, admit, install_thread_hooks
from lifecycle.middleware import ActivityMiddleware


class ActivityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.calls = []
        self.tracker = Tracker('unused', 'source', 'pod', transport=lambda op, data: self.calls.append((op, data)))

    async def test_stream_and_detached_agent_survive_client_disconnect(self):
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        loop.set_task_factory(task_factory)
        self.addCleanup(loop.set_task_factory, original)
        release = asyncio.Event()
        detached = []
        async def agent():
            await release.wait()
        async def app(scope, receive, send):
            await send({'type': 'http.response.start', 'status': 200})
            detached.append(asyncio.create_task(agent()))
            await send({'type': 'http.response.body', 'body': b'first', 'more_body': True})
            raise asyncio.CancelledError()
        async def send(message):
            if message['type'] == 'http.response.body':
                self.assertTrue(self.tracker.tickets)
        with self.assertRaises(asyncio.CancelledError):
            await ActivityMiddleware(app, self.tracker)({'type': 'http', 'path': '/api/chat', 'method': 'POST'}, None, send)
        self.tracker.report()
        self.assertNotIn('finish', [op for op, _ in self.calls])
        release.set()
        await detached[0]
        await asyncio.sleep(0)
        self.tracker.report()
        self.assertFalse(self.tracker.tickets)

    async def test_task_cancelled_before_first_instruction_releases_reference(self):
        loop = asyncio.get_running_loop()
        original = loop.get_task_factory()
        loop.set_task_factory(task_factory)
        self.addCleanup(loop.set_task_factory, original)
        work = self.tracker.begin()
        token = CURRENT.set(work)
        try:
            task = asyncio.create_task(asyncio.sleep(100))
        finally:
            CURRENT.reset(token)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        work.release()
        self.tracker.report()
        self.assertFalse(self.tracker.tickets)

    async def test_passive_browser_heartbeat_does_not_admit_work(self):
        async def app(*args):
            return 'passive'
        result = await ActivityMiddleware(app, self.tracker)(
            {'type': 'http', 'path': '/api/activity/heartbeat', 'method': 'POST'}, None, None)
        self.assertEqual(result, 'passive')
        self.assertFalse(self.calls)

    async def test_scheduled_execution_requires_fresh_root_admission(self):
        work = self.tracker.begin()
        token = CURRENT.set(work)
        self.tracker.transport = lambda *args: (_ for _ in ()).throw(AdmissionClosed())
        @scheduled(self.tracker)
        async def job():
            self.fail('draining admitted a new scheduled execution')
        try:
            with self.assertRaises(AdmissionClosed):
                await job()
        finally:
            CURRENT.reset(token)
            work.release()

    async def test_disconnect_during_admission_retires_late_acknowledgement(self):
        entered, release = threading.Event(), threading.Event()
        def transport(operation, payload):
            if operation == 'begin':
                entered.set()
                release.wait(2)
        self.tracker.transport = transport
        task = asyncio.create_task(admit(self.tracker))
        while not entered.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        release.set()
        for _ in range(100):
            if self.tracker.tickets and all(value == 0 for value in self.tracker.tickets.values()):
                break
            await asyncio.sleep(0.001)
        self.tracker.report()
        self.assertFalse(self.tracker.tickets)


class ThreadActivityTests(unittest.TestCase):
    def test_idle_pool_threads_are_excluded_but_submitted_work_is_retained(self):
        from concurrent.futures import ThreadPoolExecutor
        tracker = Tracker('unused', 'source', 'pod', transport=lambda *args: {})
        original_submit, original_start = install_thread_hooks()
        self.addCleanup(setattr, ThreadPoolExecutor, 'submit', original_submit)
        self.addCleanup(setattr, threading.Thread, 'start', original_start)
        release = threading.Event()
        work = tracker.begin()
        token = CURRENT.set(work)
        with ThreadPoolExecutor(max_workers=1) as pool:
            try:
                future = pool.submit(release.wait, 2)
            finally:
                CURRENT.reset(token)
                work.release()
            tracker.report()
            self.assertTrue(tracker.tickets)
            release.set()
            future.result(timeout=2)
            tracker.report()
            self.assertFalse(tracker.tickets)
