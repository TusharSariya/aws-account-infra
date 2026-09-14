"""Supervise admitted subprocess trees without host privileges or shared PID namespaces."""
import json
import os
from pathlib import Path
import signal
import select
import subprocess
import sys
import threading

from .tracking import CURRENT


def install_process_hook():
    original = subprocess.Popen
    helper = str(Path(__file__).with_name('supervise.py'))

    class SupervisedPopen(original):
        def __init__(self, args, *positional, **kwargs):
            self.homelab_work = CURRENT.get()
            self.homelab_supervised = False
            if self.homelab_work is None:
                super().__init__(args, *positional, **kwargs)
                return
            if positional:
                raise ValueError('Admitted subprocess options must use explicit keyword arguments')
            preexec = kwargs.get('preexec_fn')
            if preexec not in (None, os.setsid):
                raise ValueError('Unreviewed subprocess pre-exec hook')
            command = [os.fsdecode(args)] if isinstance(args, (str, bytes, os.PathLike)) else [os.fsdecode(arg) for arg in args]
            executable = kwargs.pop('executable', None)
            if kwargs.pop('shell', False):
                command = [os.fsdecode(executable or '/bin/sh'), '-c', *command]
                executable = None
            env = dict(os.environ if kwargs.get('env') is None else kwargs['env'])
            env['HOMELAB_WORK_ID'] = self.homelab_work.ticket
            ready_read, ready_write = os.pipe()
            env['HOMELAB_SUPERVISOR_READY_FD'] = str(ready_write)
            kwargs['env'] = env
            kwargs['pass_fds'] = (*kwargs.get('pass_fds', ()), ready_write)
            self.homelab_work.retain()
            try:
                super().__init__([sys.executable, helper, json.dumps({'args': command,
                    'executable': os.fsdecode(executable) if executable else None})], **kwargs)
                os.close(ready_write)
                ready_write = None
                if not select.select([ready_read], [], [], 5)[0] or os.read(ready_read, 1) != b'R':
                    self.homelab_work.tracker.known = False
                    super().kill()
                    raise RuntimeError('Subprocess supervisor did not establish lifetime tracking')
                self.homelab_supervised = True
            except BaseException:
                self.homelab_work.release()
                raise
            finally:
                os.close(ready_read)
                if ready_write is not None:
                    os.close(ready_write)
            # A separate waiter preserves tracking if the caller returns or loses
            # its Process object. Popen serializes concurrent wait/poll calls.
            def observed_exit():
                code = self.wait()
                if code < 0:
                    # A killed supervisor cannot attest to descendant completion.
                    self.homelab_work.tracker.known = False
                else:
                    self.homelab_work.release()
            context = CURRENT.set(None)
            try:
                threading.Thread(target=observed_exit, daemon=True, name='admitted-process-reaper').start()
            finally:
                CURRENT.reset(context)

        def send_signal(self, sig):
            if self.homelab_supervised and sig == signal.SIGKILL:
                sig = signal.SIGUSR1  # Kill descendants while retaining the reaper.
            return super().send_signal(sig)

    subprocess.Popen = SupervisedPopen
    return original
