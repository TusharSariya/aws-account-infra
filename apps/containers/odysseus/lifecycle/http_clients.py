"""Attach local model credentials and admitted-work identity only to fixed services."""
from urllib.parse import urlsplit
from copy import copy

from .tracking import CURRENT


def target(url):
    parsed = urlsplit(str(url))
    if parsed.scheme != 'http' or parsed.username or parsed.password:
        return None
    if parsed.port == 11434 and parsed.hostname in ('localhost', '127.0.0.1', 'ollama.homelab-models.svc'):
        return 'model'
    if parsed.port == 7000 and parsed.hostname in ('localhost', '127.0.0.1', 'odysseus.homelab-models.svc'):
        return 'workspace'
    return None


def inject(url, headers, model_token):
    kind = target(url)
    if kind is None:
        return None
    if kind == 'model':
        headers['Authorization'] = 'Bearer ' + model_token
    work = CURRENT.get()
    if work is not None:
        headers['X-Homelab-Work'] = work.ticket
    else:
        headers.pop('X-Homelab-Work', None)
    return kind


def install_http_hooks(model_token):
    import httpx
    import requests
    original_sync, original_async = httpx.Client.send, httpx.AsyncClient.send
    original_requests = requests.Session.send

    def sync(client, request, **kwargs):
        if target(request.url) is None:
            return original_sync(client, request, **kwargs)
        request = copy(request)
        request.headers = request.headers.copy()
        request.extensions = request.extensions.copy()
        kind = inject(request.url, request.headers, model_token)
        if kind:
            kwargs['follow_redirects'] = False
            if kind == 'model':
                kwargs['auth'] = None
        return original_sync(client, request, **kwargs)

    async def asynchronous(client, request, **kwargs):
        if target(request.url) is None:
            return await original_async(client, request, **kwargs)
        request = copy(request)
        request.headers = request.headers.copy()
        request.extensions = request.extensions.copy()
        kind = inject(request.url, request.headers, model_token)
        if kind:
            kwargs['follow_redirects'] = False
            if kind == 'model':
                kwargs['auth'] = None
        return await original_async(client, request, **kwargs)

    def send(session, request, **kwargs):
        if target(request.url) is None:
            return original_requests(session, request, **kwargs)
        request = request.copy()
        if inject(request.url, request.headers, model_token):
            kwargs['allow_redirects'] = False
        return original_requests(session, request, **kwargs)

    httpx.Client.send, httpx.AsyncClient.send, requests.Session.send = sync, asynchronous, send
    return original_sync, original_async, original_requests
