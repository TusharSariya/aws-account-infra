"""Install reviewed hooks before the pinned app registers startup work."""
import asyncio
from functools import wraps
import os
from pathlib import Path
import threading
import time

from .http_clients import install_http_hooks
from .identity import serve as serve_identity
from .middleware import ActivityMiddleware
from .processes import install_process_hook
from .tracking import Tracker, scheduled, task_factory, install_thread_hooks

tracker = None


def configure(app, internal_token):
    global tracker
    endpoint = os.environ.get('HOMELAB_LIFECYCLE_URL')
    if endpoint != 'http://ai-lifecycle.homelab-platform.svc:8080' or not os.environ.get('POD_UID'):
        raise RuntimeError('Fixed lifecycle endpoint and Pod identity required')
    source = Path('/credentials/lifecycle-token').read_text().strip()
    model = Path('/credentials/model-workspace-token').read_text().strip()
    if min(len(source), len(model)) < 43 or source == model:
        raise RuntimeError('Separate workspace and activity credentials required')
    if tracker is not None:
        raise RuntimeError('Activity hooks already installed')
    tracker = Tracker(endpoint, source, os.environ['POD_UID'])
    serve_identity(tracker)
    install_thread_hooks()
    install_process_hook()
    install_http_hooks(model)
    app.add_middleware(ActivityMiddleware, tracker=tracker, internal_token=internal_token)

    async def startup():
        loop = asyncio.get_running_loop()
        if loop.get_task_factory() is not None:
            raise RuntimeError('Unreviewed task factory would bypass lifecycle tracking')
        loop.set_task_factory(task_factory)
        def report():
            while True:
                try:
                    tracker.report()
                except Exception:
                    print('Workspace activity publication unavailable', flush=True)
                time.sleep(3)
        threading.Thread(target=report, daemon=True, name='workspace-activity').start()
    app.add_event_handler('startup', startup)


def scheduled_work(function):
    @wraps(function)
    async def run(*args, **kwargs):
        return await scheduled(tracker)(function)(*args, **kwargs)
    return run
