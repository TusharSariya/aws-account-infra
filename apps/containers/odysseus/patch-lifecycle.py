#!/usr/bin/env python3
"""Apply exact reviewed hooks to checksum-verified Odysseus source."""
from pathlib import Path
import sys


def patch(source):
    def replace(path, old, new):
        file = source / path
        text = file.read_text()
        if text.count(old) != 1:
            raise ValueError('Pinned activity hook changed: ' + path)
        file.write_text(text.replace(old, new))
    replace('app.py', 'app.add_middleware(_RequestTimeoutMiddleware)',
        'from lifecycle.bootstrap import configure as configure_lifecycle\n'
        'from core.middleware import INTERNAL_TOOL_TOKEN as lifecycle_internal_token\n'
        'configure_lifecycle(app, lifecycle_internal_token)\n\n'
        'app.add_middleware(_RequestTimeoutMiddleware)')
    replace('app.py', 'app.router.lifespan_context = _lifespan',
        'from lifecycle.bootstrap import lifespan as lifecycle_lifespan\n'
        'app.router.lifespan_context = lifecycle_lifespan(_lifespan)')
    replace('src/task_scheduler.py', '    async def _execute_task(self,',
        '    async def _execute_task(self,')  # Assert one reviewed scheduler entry point.
    replace('src/task_scheduler.py', '        try:\n            if bypass_model_slot or not self._task_needs_model_slot(task_id):',
        '        from lifecycle.tracking import admit, CURRENT, AdmissionClosed\n'
        '        from lifecycle.bootstrap import tracker\n'
        '        lifecycle_work = lifecycle_context = None\n'
        '        try:\n'
        '            lifecycle_work = await admit(tracker)\n'
        '            lifecycle_context = CURRENT.set(lifecycle_work)\n'
        '            if bypass_model_slot or not self._task_needs_model_slot(task_id):')
    replace('src/task_scheduler.py', '        except asyncio.CancelledError:\n            # If cancellation happens while queued',
        '        except AdmissionClosed:\n'
        '            self._mark_run_aborted(task_id, run_id)\n'
        '            self._defer_immediately_due_task(task_id, delay=timedelta(minutes=15))\n'
        '        except asyncio.CancelledError:\n            # If cancellation happens while queued')
    replace('src/task_scheduler.py', '        finally:\n            handle = self._task_handles.get(task_id)',
        '        finally:\n'
        '            if lifecycle_context is not None:\n                CURRENT.reset(lifecycle_context)\n'
        '            if lifecycle_work is not None:\n                lifecycle_work.release()\n'
        '            handle = self._task_handles.get(task_id)')
    replace('routes/skills_routes.py', 'async def run_scheduled_skill_audit(',
        'from lifecycle.bootstrap import scheduled_work\n\n@scheduled_work\nasync def run_scheduled_skill_audit(')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
