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
    # Status refreshes must not turn retained terminal history into new work.
    # Keep explicit one-shot recovery and general shell execution admitted.
    replace('static/js/cookbookRunning.js',
        'function _hasLiveTasks(tasks = null) {',
        "function _lifecycleTerminal(task) {\n  return ['done', 'completed', 'stopped', 'error', 'crashed', 'failed', 'ended', 'killed'].includes(String(task.status || '').toLowerCase());\n}\n\nfunction _hasLiveTasks(tasks = null) {")
    replace('static/js/cookbookRunning.js',
        "    || _downloadOutputLooksActive(t)\n  );",
        "    || (!_lifecycleTerminal(t) && _downloadOutputLooksActive(t))\n  );")
    replace('static/js/cookbookRunning.js',
        'export function _startBackgroundMonitor() {\n  if (_bgMonitorInterval) return;',
        'export function _startBackgroundMonitor() {\n  if (!_hasLiveTasks()) return;\n  if (_bgMonitorInterval) return;')
    replace('static/js/cookbookRunning.js',
        '  _bgMonitorInterval = setInterval(() => {\n    if (!_canBackgroundPoll()) return;',
        '  _bgMonitorInterval = setInterval(() => {\n    if (!_hasLiveTasks()) { _stopBackgroundMonitor(); return; }\n    if (!_canBackgroundPoll()) return;')
    replace('static/js/cookbookRunning.js',
        'if (_hasLiveTasks() || _isRunningTabVisible()) {',
        'if (_hasLiveTasks()) {')
    replace('static/js/cookbookRunning.js',
        'async function _pollBackgroundStatus() {\n  if (!_canBackgroundPoll() || _bgPollInFlight) return;',
        'async function _pollBackgroundStatus() {\n  if (!_hasLiveTasks()) { _stopBackgroundMonitor(); return; }\n  if (!_canBackgroundPoll() || _bgPollInFlight) return;')
    replace('static/js/cookbookRunning.js',
        '    if (errorTasks.length > 0) {\n      _showCookbookNotif(true);',
        '    if (activeTasks.length === 0) _stopBackgroundMonitor();\n    if (errorTasks.length > 0) {\n      _showCookbookNotif(true);')
    replace('static/js/cookbookRunning.js',
        "    document.dispatchEvent(new CustomEvent('cookbook:state-synced', { detail: state }));",
        "    _startBackgroundMonitor();\n    document.dispatchEvent(new CustomEvent('cookbook:state-synced', { detail: state }));")
    replace('static/js/cookbookRunning.js',
        'async function _reconnectTask(el, task) {\n  if (!el || !task) return;',
        "async function _reconnectTask(el, task) {\n  if (!el || !task || _lifecycleTerminal(task)) return;")
    replace('static/js/cookbookRunning.js',
        '  while (!controller.signal.aborted) {\n    const liveWrap',
        "  while (!controller.signal.aborted) {\n    const current = _loadTasks().find(t => t.sessionId === task.sessionId);\n    if (!current || _lifecycleTerminal(current)) { controller.abort(); break; }\n    const liveWrap")
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
    replace('src/bg_monitor.py', 'async def _run_followup(rec: dict) -> bool:',
        'from lifecycle.bootstrap import scheduled_work\n\n@scheduled_work\nasync def _run_followup(rec: dict) -> bool:')
    replace('src/bg_monitor.py', '_monitor_task = asyncio.create_task(_loop())',
        'from contextvars import Context\n    _monitor_task = asyncio.create_task(_loop(), context=Context())')
    replace('routes/email_pollers.py', '_poller_task = loop.create_task(_scheduled_email_poller())',
        'from contextvars import Context\n            _poller_task = loop.create_task(_scheduled_email_poller(), context=Context())')
    replace('routes/email_pollers.py', '        for r in rows:\n            sid = r[0]\n            try:',
        '        from lifecycle.tracking import CURRENT, AdmissionClosed\n'
        '        from lifecycle.bootstrap import tracker\n'
        '        for r in rows:\n'
        '            sid = r[0]\n'
        '            if tracker is None:\n'
        '                raise AdmissionClosed("Scheduled delivery requires the instrumented server")\n'
        '            lifecycle_work = tracker.begin()\n'
        '            lifecycle_context = CURRENT.set(lifecycle_work)\n'
        '            try:')
    replace('routes/email_pollers.py', '                failed.append({"id": sid, "error": str(e)})',
        '                failed.append({"id": sid, "error": str(e)})\n'
        '            finally:\n'
        '                CURRENT.reset(lifecycle_context)\n'
        '                lifecycle_work.release()')
    replace('routes/skills_routes.py', 'async def run_scheduled_skill_audit(',
        'from lifecycle.bootstrap import scheduled_work\n\n@scheduled_work\nasync def run_scheduled_skill_audit(')


if __name__ == '__main__':
    patch(Path(sys.argv[1]))
