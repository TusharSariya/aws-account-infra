#!/usr/bin/env python3
"""Exercise pinned scheduler admission, queue cancellation and deferred work."""
import ast
import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch
import uuid

SOURCE = Path(sys.argv.pop(1))
sys.path.insert(0, str(SOURCE))
from lifecycle.tracking import Tracker, CURRENT, AdmissionClosed


class SchedulerTests(unittest.IsolatedAsyncioTestCase):
    async def test_closed_admission_defers_and_queue_cancellation_retires_work(self):
        module = ast.parse((SOURCE / 'src/task_scheduler.py').read_text())
        scheduler = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == 'TaskScheduler')
        method = next(node for node in scheduler.body if isinstance(node, ast.AsyncFunctionDef) and node.name == '_execute_task')
        scope = {'asyncio': asyncio, 'uuid': uuid, 'timedelta': timedelta,
                 '_utcnow': lambda: datetime.now(timezone.utc), 'logger': Mock()}
        exec(compile(ast.Module(body=[method], type_ignores=[]), 'pinned_scheduler', 'exec'), scope)
        database = ModuleType('core.database')
        database.SessionLocal = Mock()
        database.TaskRun = lambda **values: SimpleNamespace(**values)
        calls = []
        tracker = Tracker('fixture', 'fixture', 'fixture', transport=lambda operation, payload: calls.append(operation))
        bootstrap = ModuleType('lifecycle.bootstrap')
        bootstrap.tracker = tracker
        runner = SimpleNamespace(_task_handles={}, _executing={'fixture'}, _executing_lock=asyncio.Lock(),
            _run_semaphore=asyncio.Semaphore(0), _task_needs_model_slot=lambda _: True,
            _execute_task_locked=AsyncMock(), _mark_run_aborted=Mock(), _defer_immediately_due_task=Mock())
        with patch.dict(sys.modules, {'core.database': database, 'lifecycle.bootstrap': bootstrap}):
            tracker.transport = Mock(side_effect=AdmissionClosed('draining'))
            await scope['_execute_task'](runner, 'fixture')
            runner._execute_task_locked.assert_not_awaited()
            runner._mark_run_aborted.assert_called_once()
            self.assertEqual(runner._defer_immediately_due_task.call_args.kwargs['delay'], timedelta(minutes=15))
            self.assertFalse(runner._task_handles)
            self.assertFalse(runner._executing)
            tracker.transport = lambda operation, payload: calls.append(operation)
            tracker.report()
            calls.clear()
            queued = asyncio.create_task(scope['_execute_task'](runner, 'fixture'))
            for _ in range(100):
                if tracker.tickets:
                    break
                await asyncio.sleep(.01)
            self.assertTrue(tracker.tickets)
            runner._execute_task_locked.assert_not_awaited()
            queued.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await queued
            tracker.report()
            self.assertFalse(tracker.tickets)
            self.assertEqual(calls.count('begin'), 1)
            self.assertEqual(calls.count('finish'), 1)
            self.assertFalse(runner._task_handles)
            self.assertIsNone(CURRENT.get())
            async def execute(*args, **kwargs):
                self.assertIsNotNone(CURRENT.get())
                self.assertEqual(len(tracker.tickets), 1)
            runner._execute_task_locked = execute
            await scope['_execute_task'](runner, 'fixture', bypass_model_slot=True)
            tracker.report()
            self.assertFalse(tracker.tickets)
            self.assertIsNone(CURRENT.get())


if __name__ == '__main__':
    unittest.main()
