import os
from pathlib import Path
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'apps/containers/odysseus'))
from lifecycle.tracking import Tracker, CURRENT
from lifecycle.processes import install_process_hook


@unittest.skipUnless(sys.platform == 'linux', 'Linux subreaper acceptance runs in the pinned image')
class ProcessTests(unittest.TestCase):
    def setUp(self):
        self.tracker = Tracker('unused', 'source', 'pod', transport=lambda *args: {})
        self.original = install_process_hook()
        self.addCleanup(setattr, subprocess, 'Popen', self.original)

    def launch(self, code):
        work = self.tracker.begin()
        token = CURRENT.set(work)
        try:
            process = subprocess.Popen([sys.executable, '-c', code], stdout=subprocess.PIPE)
        finally:
            CURRENT.reset(token)
            work.release()
        self.addCleanup(process.stdout.close)
        return process

    def wait_retired(self):
        for _ in range(200):
            self.tracker.report()
            if not self.tracker.tickets:
                return
            time.sleep(0.01)
        self.fail('completed subprocess tree was not retired')

    def test_detached_grandchild_remains_tracked_after_original_parent_exits(self):
        process = self.launch("import os,time; pid=os.fork(); os._exit(0) if pid else None; os.setsid(); time.sleep(0.4)")
        time.sleep(0.15)
        self.tracker.report()
        self.assertIsNone(process.poll())
        self.assertTrue(self.tracker.tickets)
        self.assertEqual(process.wait(timeout=3), 0)
        self.wait_retired()
        self.assertTrue(self.tracker.known)

    def test_kill_reaps_descendants_before_tracking_finishes(self):
        process = self.launch("import os,time; pid=os.fork(); os._exit(0) if pid else None; os.setsid(); time.sleep(100)")
        time.sleep(0.15)
        process.kill()
        self.assertEqual(process.wait(timeout=3), 137)
        self.wait_retired()
        self.assertTrue(self.tracker.known)
