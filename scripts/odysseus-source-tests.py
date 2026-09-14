#!/usr/bin/env python3
"""Exercise patched pinned functions with disposable SQLite and no external delivery."""
import ast
import asyncio
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import html
import importlib.util
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import tempfile
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import Mock

SOURCE = Path(sys.argv.pop(1))
sys.path.insert(0, str(SOURCE))
from lifecycle.tracking import Tracker, CURRENT, AdmissionClosed, scheduled

bootstrap = ModuleType('lifecycle.bootstrap')
sys.modules['lifecycle.bootstrap'] = bootstrap


def function(path, name, scope):
    module = ast.parse((SOURCE / path).read_text())
    node = next(node for node in module.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)
    exec(compile(ast.Module(body=[node], type_ignores=[]), str(SOURCE / path), 'exec'), scope)
    return scope[name]


class BrowserPollingTests(unittest.TestCase):
    def test_terminal_history_stops_timers_without_shell_probes_and_live_tasks_resume(self):
        source = (SOURCE / 'static/js/cookbookRunning.js').read_text()
        # Execute the actual pinned monitor functions with deterministic browser timers.
        start = source.index('export function _startBackgroundMonitor()')
        end = source.index('// Retry-probe', start)
        monitor = source[start:end].replace('export function', 'function')
        script = r"""
const assert = require('node:assert/strict');
let live = false, interval = null, polls = 0, probes = 0, heals = 0;
let _bgMonitorInterval = null;
const BG_MONITOR_INTERVAL_MS = 10000;
const document = {getElementById: () => null};
const _hasLiveTasks = () => live;
const _canBackgroundPoll = () => true;
const _isRunningTabVisible = () => true;
const _pollBackgroundStatus = () => { polls++; };
const _checkServeReachability = () => { probes++; };
const _selfHealStaleTasks = async () => { heals++; };
const setInterval = callback => { interval = callback; return 1; };
const clearInterval = () => { interval = null; };
""" + monitor + r"""
_startBackgroundMonitor();
assert.equal(interval, null);
assert.deepEqual([polls, probes, heals], [0, 0, 0]);
live = true;
_startBackgroundMonitor();
assert.equal(typeof interval, 'function');
assert.deepEqual([polls, probes, heals], [1, 1, 0]);
interval();
assert.deepEqual([polls, probes, heals], [2, 2, 1]);
live = false;
interval();
assert.equal(interval, null);
assert.deepEqual([polls, probes, heals], [2, 2, 1]);
_startBackgroundMonitor();
assert.equal(interval, null);
live = true;
_startBackgroundMonitor();
assert.deepEqual([polls, probes, heals], [3, 3, 1]);
"""
        subprocess.run(['node', '-e', script], check=True)


class BrowserRecoveryTests(unittest.TestCase):
    def test_state_sync_discovers_work_and_terminal_cards_do_not_reconnect(self):
        source = (SOURCE / 'static/js/cookbookRunning.js').read_text()
        def between(start, end):
            return source[source.index(start):source.index(end, source.index(start))].replace('export async function', 'async function').replace('export function', 'function')
        functions = between('function _downloadOutputLooksActive(', 'function _canClearTask(')
        functions += between('export async function _syncFromServer()', '// ── Retry download')
        functions += between('async function _reconnectTask(el, task)', '// ── Background monitor')
        functions += between('function _lifecycleTerminal(', 'function _isRunningTabVisible(')
        functions += between('export function _startBackgroundMonitor()', '// Retry-probe')
        script = r"""
const assert = require('node:assert/strict');
let tasks = [], serverTasks = [], interval = null, polls = 0, shellCalls = 0;
let _bgMonitorInterval = null;
const BG_MONITOR_INTERVAL_MS = 10000;
const TASKS_KEY = 'tasks';
const _envState = {};
const _loadTasks = () => tasks;
const _loadTombstones = () => ({});
const _saveTombstones = () => {};
const _isTombstoned = () => false;
const _redactTaskForStorage = task => task;
const _normalizeState = state => state;
const _canBackgroundPoll = () => true;
const _isRunningTabVisible = () => true;
const _pollBackgroundStatus = () => { polls++; };
const _checkServeReachability = () => {};
const _selfHealStaleTasks = async () => {};
const _tmuxCmd = (_, cmd) => cmd;
const localStorage = {setItem: (key, value) => { if (key === TASKS_KEY) tasks = JSON.parse(value); }};
const document = {dispatchEvent: () => {}, getElementById: () => null};
const CustomEvent = class {};
const setInterval = callback => { interval = callback; return 1; };
const clearInterval = () => { interval = null; };
const setTimeout = callback => callback();
const fetch = async path => {
  if (path === '/api/cookbook/state') return {ok: true, json: async () => ({env: {}, tasks: serverTasks})};
  assert.equal(path, '/api/shell/exec');
  shellCalls++;
  tasks[0].status = 'done';
  throw Error('terminal transition while request is in flight');
};
""" + functions + r"""
(async () => {
  serverTasks = [{sessionId: 'history', status: 'done'}];
  assert.equal(await _syncFromServer(), true);
  assert.equal(interval, null);
  serverTasks.push({sessionId: 'server-work', status: 'running'});
  assert.equal(await _syncFromServer(), true);
  assert.equal(typeof interval, 'function');
  assert.equal(polls, 1);
  for (const status of ['done', 'completed', 'error', 'crashed', 'stopped', 'failed', 'ended', 'killed']) {
    assert.equal(_hasLiveTasks([{status, type: 'download', output: 'model-00012-of-00082.safetensors: 56%|'}]), false);
    await _reconnectTask({querySelector: () => { throw Error('terminal card reconnect'); }}, {status});
  }
  assert.equal(shellCalls, 0);
  tasks = [{sessionId: 'live', status: 'running'}];
  const el = {isConnected: true, querySelector: () => ({classList: {contains: () => false}})};
  await _reconnectTask(el, {...tasks[0]});
  assert.equal(shellCalls, 1);
  assert.equal(el._abort.signal.aborted, true);
})().catch(error => { console.error(error); process.exitCode = 1; });
"""
        subprocess.run(['node', '-e', script], check=True)


class ScheduledEmailTests(unittest.TestCase):
    def test_due_delivery_is_admitted_before_claim_and_rejected_delivery_stays_pending(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / 'scheduled.db'
            with sqlite3.connect(database) as conn:
                conn.execute('CREATE TABLE scheduled_emails (id TEXT, to_addr TEXT, cc TEXT, bcc TEXT, subject TEXT, body TEXT, in_reply_to TEXT, references_hdr TEXT, attachments TEXT, account_id TEXT, odysseus_kind TEXT, owner TEXT, status TEXT, send_at TEXT, error TEXT)')
                conn.execute("INSERT INTO scheduled_emails VALUES ('fixture', 'recipient@example.invalid', '', '', 'fixture', 'body', '', '', '[]', '', 'scheduled', 'fixture', 'pending', '2000-01-01', '')")
            tracker = Tracker('fixture', 'fixture', 'fixture', transport=lambda *args: {})
            bootstrap.tracker = tracker
            delivered = []
            def delivery(*args):
                self.assertIsNotNone(CURRENT.get())
                self.assertEqual(len(tracker.tickets), 1)
                delivered.append('fixture')
            poll = function('routes/email_pollers.py', '_scheduled_poll_once', {
                'datetime': datetime, 'SCHEDULED_DB': str(database), 'json': json,
                'MIMEMultipart': MIMEMultipart, 'MIMEText': MIMEText, 're': re, 'html': html,
                '_get_email_config': lambda *args, **kwargs: {'from_address': 'sender@example.invalid'},
                '_owner_for_email_account': lambda *args: 'fixture', '_send_smtp_message': delivery,
                '_imap': Mock(side_effect=OSError('disposable fixture has no IMAP')),
                '_cleanup_compose_uploads': lambda *args: None, 'logger': Mock()})
            tracker.transport = Mock(side_effect=AdmissionClosed('draining'))
            self.assertIn('error', poll())
            self.assertFalse(delivered)
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT status FROM scheduled_emails').fetchone()[0], 'pending')
            tracker.transport = lambda *args: {}
            tracker.report()
            self.assertEqual(poll()['sent'], ['fixture'])
            self.assertEqual(delivered, ['fixture'])
            tracker.report()
            self.assertFalse(tracker.tickets)
            with sqlite3.connect(database) as conn:
                self.assertEqual(conn.execute('SELECT status FROM scheduled_emails').fetchone()[0], 'sent')


class BackgroundAgentTests(unittest.IsolatedAsyncioTestCase):
    async def test_followup_spans_agent_tools_and_persistence_and_defers_when_closed(self):
        tracker = Tracker('fixture', 'fixture', 'fixture', transport=lambda *args: {})
        bootstrap.tracker = tracker
        manager = Mock()
        manager.get_session.return_value = SimpleNamespace(id='fixture', model='fixture', get_context_messages=lambda: [])
        manager.add_message.side_effect = lambda *args: self.assertIsNotNone(CURRENT.get())
        manager.save_sessions.side_effect = lambda: self.assertEqual(len(tracker.tickets), 1)
        ai = ModuleType('src.ai_interaction')
        ai.get_session_manager = lambda: manager
        core_models = ModuleType('core.models')
        core_models.ChatMessage = lambda *args, **kwargs: None
        source_package = ModuleType('src')
        source_package.agent_runs = SimpleNamespace(is_active=lambda *args: False)
        sys.modules.update({'src': source_package, 'src.ai_interaction': ai,
                            'core': ModuleType('core'), 'core.models': core_models})
        entered, release = asyncio.Event(), asyncio.Event()
        async def drain(*args):
            self.assertIsNotNone(CURRENT.get())
            entered.set()
            await release.wait()
            return 'fixture', []
        followup = function('src/bg_monitor.py', '_run_followup', {
            'scheduled_work': scheduled(tracker), 'logger': Mock(), '_drain_agent': drain,
            '_background_result_message': lambda *args: 'fixture',
            'bg_jobs': SimpleNamespace(result_text=lambda *args: 'fixture')})
        tracker.transport = Mock(side_effect=AdmissionClosed('draining'))
        with self.assertRaises(AdmissionClosed):
            await followup({'id': 'fixture', 'session_id': 'fixture'})
        manager.get_session.assert_not_called()
        tracker.transport = lambda *args: {}
        tracker.report()
        task = asyncio.create_task(followup({'id': 'fixture', 'session_id': 'fixture'}))
        await asyncio.wait_for(entered.wait(), 2)
        self.assertEqual(len(tracker.tickets), 1)
        release.set()
        self.assertTrue(await task)
        tracker.report()
        self.assertFalse(tracker.tickets)


if __name__ == '__main__':
    unittest.main()
