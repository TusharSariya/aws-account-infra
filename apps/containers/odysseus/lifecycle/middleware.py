"""Pure ASGI tracking lasts through the final streamed body and cancellation."""
import asyncio
import json
import secrets

from .tracking import AdmissionClosed, CURRENT, admit

PASSIVE = {
    '/api/health', '/api/activity/heartbeat', '/api/client-perf', '/api/tasks/notifications',
    '/api/tasks/runs/recent', '/api/research/active', '/api/email/urgency-state',
    '/api/email/unread-state', '/api/auth/login', '/api/auth/logout',
    '/api/auth/status', '/api/auth/policy',
}


def passive(scope):
    path = scope.get('path', '')
    if path in PASSIVE:
        return True
    return scope.get('method') in ('GET', 'HEAD') and (
        path in ('/', '/health', '/healthz', '/favicon.ico') or
        path.startswith(('/static/', '/api/health/', '/api/chat/stream_status', '/api/prefs/')))


class ActivityMiddleware:
    def __init__(self, app, tracker, internal_token=None):
        self.app, self.tracker, self.internal_token = app, tracker, internal_token

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or passive(scope):
            return await self.app(scope, receive, send)
        # The auth middleware remains outside this layer, so rejected unauthenticated
        # requests cannot reset idle time or gain an admitted work identity.
        try:
            headers = {key.lower(): value for key, value in scope.get('headers', [])}
            internal = headers.get(b'x-odysseus-internal-token', b'')
            parent = headers.get(b'x-homelab-work', b'').decode('ascii', errors='replace')
            if (parent and self.internal_token and
                    secrets.compare_digest(internal, self.internal_token.encode())):
                work = self.tracker.join(parent)
            else:
                work = await admit(self.tracker)
        except AdmissionClosed:
            body = json.dumps({'detail': 'AI is draining or new work is blocked; inspect lifecycle Status'}).encode()
            await send({'type': 'http.response.start', 'status': 503,
                        'headers': [(b'content-type', b'application/json'), (b'retry-after', b'30')]})
            return await send({'type': 'http.response.body', 'body': body})
        token = CURRENT.set(work)
        try:
            await self.app(scope, receive, send)
        finally:
            CURRENT.reset(token)
            work.release()
