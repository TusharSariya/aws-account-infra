"""Read-only dependency transport: two Nexus attempts, then three upstream attempts.

A connection-level Nexus failure (unreachable host, timeout) sidelines the cache
for CACHE_DOWN_SECONDS so off-cluster runners go straight upstream.

Package managers still verify signatures and hashes. A complete response is never
retried here for an integrity failure: only transport failures trigger fallback.
No caller headers, credentials, or write requests are forwarded.
"""
import argparse
import http.client
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

CACHE = 'http://nexus.homelab-cache.svc.cluster.local:8081/repository/'
# How long one connection-level cache failure sidelines Nexus (seconds).
CACHE_DOWN_SECONDS = 300
ORIGINS = {
    'npm': 'https://registry.npmjs.org/',
    'apt-git-core': 'https://ppa.launchpadcontent.net/git-core/ppa/ubuntu/',
    'go': 'https://proxy.golang.org/',
    'apt-ubuntu': 'https://archive.ubuntu.com/ubuntu/',
    'apt-ubuntu-security': 'https://security.ubuntu.com/ubuntu/',
    'apt-debian': 'https://deb.debian.org/debian/',
    'apt-debian-security': 'https://security.debian.org/debian-security/',
    'pypi': 'https://pypi.org/',
    'raw-python-files': 'https://files.pythonhosted.org/',
}


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != 'https' or target.username or target.password:
            raise ValueError('Unsafe dependency redirect')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class Transport:
    def __init__(self, cache=CACHE, opener=None):
        self.cache = cache
        self.opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), SafeRedirect())
        self.cache_opener = opener or urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect())
        # Off-cluster runners (the operator containers) cannot reach Nexus at
        # all. One connection-level failure sidelines the cache for a while so a
        # job does not pay two timeouts per artifact; HTTP misses never trip it.
        self.cache_down_until = 0.0

    def download(self, cache_url, upstream_url):
        """Return a seekable complete body; upstream_url may resolve lazily."""
        last = None
        for source, count in [('cache', 2), ('upstream', 3)]:
            if source == 'cache' and time.monotonic() < self.cache_down_until:
                continue
            url = cache_url if source == 'cache' else None
            for attempt in range(count):
                body = tempfile.TemporaryFile()
                try:
                    if url is None:
                        url = upstream_url() if callable(upstream_url) else upstream_url
                    request = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
                    selected_opener = self.cache_opener if source == 'cache' else self.opener
                    with selected_opener.open(request, timeout=15) as response:
                        # Spool to scratch before sending any response bytes, allowing
                        # interrupted reads to retry without mixing partial artifacts.
                        shutil.copyfileobj(response, body, length=1024 * 1024)
                        length = body.tell()
                        declared = response.headers.get('Content-Length')
                        if declared is not None and length != int(declared):
                            raise http.client.IncompleteRead(b'', int(declared) - length)
                        content_type = response.headers.get('Content-Type', 'application/octet-stream')
                    body.seek(0)
                    return body, content_type, source, attempt + 1
                except (urllib.error.URLError, TimeoutError, ConnectionError,
                        http.client.HTTPException) as error:
                    body.close()
                    last = error
                    permanent = False
                    if isinstance(error, urllib.error.HTTPError):
                        error.close()
                        permanent = 400 <= error.code < 500 and error.code not in (408, 429)
                    elif source == 'cache' and isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError)):
                        # Unreachable cache host: switch upstream now and skip the
                        # cache for subsequent artifacts of this job. Interrupted
                        # transfers (HTTPException) still retry the cache.
                        self.cache_down_until = time.monotonic() + CACHE_DOWN_SECONDS
                        break
                    # Back off before re-trying the same source after a transient
                    # failure (1s, 2s, capped at 4s). Switching from the cache to
                    # upstream is immediate, and a permanent 4xx never waits.
                    if attempt + 1 < count and not permanent:
                        time.sleep(min(2 ** attempt, 4))
                except Exception:
                    body.close()
                    raise
        if isinstance(last, urllib.error.HTTPError):
            raise last
        raise RuntimeError('Dependency transport exhausted bounded attempts') from last

    def python_artifact(self, path):
        # Nexus rewrites PyPI files to packages/<project>/<version>/<filename>.
        # Resolve the exact filename from upstream metadata only on cache outage.
        parts = path.split('/')
        if len(parts) != 4 or parts[0] != 'packages':
            raise ValueError('Unexpected PyPI artifact path')
        _, project, version, filename = parts
        metadata_url = 'https://pypi.org/pypi/' + project + '/' + version + '/json'
        body, _, _, _ = self.download(self.cache + 'pypi/pypi/' + project + '/' + version + '/json', metadata_url)
        with body:
            metadata = json.load(body)
        suffix = '.metadata' if filename.endswith('.whl.metadata') else ''
        artifact = filename[:-len(suffix)] if suffix else filename
        candidates = [entry['url'] + suffix for entry in metadata['urls'] if entry['filename'] == urllib.parse.unquote(artifact)]
        target = urllib.parse.urlsplit(candidates[0]) if len(candidates) == 1 else None
        if target is None or target.scheme != 'https' or target.hostname != 'files.pythonhosted.org' or target.username or target.password or target.port:
            raise ValueError('Exact upstream PyPI artifact required')
        return candidates[0]

    def read(self, route):
        parsed = urllib.parse.urlsplit(route)
        if parsed.scheme or parsed.netloc:
            # APT sends absolute HTTP URIs to its explicitly configured proxy.
            # Resolve only reviewed repository origins; this is not an open proxy.
            if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password or parsed.query or parsed.fragment:
                raise ValueError('Unreviewed APT proxy request')
            if parsed.netloc == 'deb.debian.org' and parsed.path.startswith('/debian-security/'):
                return self.read('/apt-debian-security/' + parsed.path.removeprefix('/debian-security/'))
            for name, origin in ORIGINS.items():
                target = urllib.parse.urlsplit(origin)
                if name.startswith('apt-') and parsed.netloc == target.netloc and parsed.path.startswith(target.path):
                    return self.read('/' + name + '/' + parsed.path[len(target.path):])
            raise ValueError('Unreviewed APT origin')
        if parsed.query or parsed.fragment:
            raise ValueError('Only repository-relative paths are supported')
        repository, separator, path = parsed.path.lstrip('/').partition('/')
        decoded = urllib.parse.unquote(path)
        if not separator or repository not in ORIGINS or any(part in ('.', '..') for part in decoded.split('/')) or '\\' in decoded:
            raise ValueError('Unreviewed dependency route')
        upstream = ORIGINS[repository] + path
        if repository == 'pypi' and path.startswith('packages/'):
            upstream = lambda: self.python_artifact(path)
        return self.download(self.cache + repository + '/' + path, upstream)


def rewrite_metadata(body, content_type, route, base, cache):
    """Rewrite only public package URLs; retain hashes and all package metadata."""
    if route.startswith('/npm/') and 'json' in content_type:
        value = body.read().decode()
        for origin in (ORIGINS['npm'], cache + 'npm/'):
            value = value.replace(origin, base + '/npm/')
        return value.encode()
    if route.startswith('/pypi/simple/') and 'html' in content_type:
        return body.read().replace(b'https://files.pythonhosted.org/',
                                   (base + '/raw-python-files/').encode())
    return None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def do_GET(self):
        if self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'ready')
            return
        try:
            body, content_type, source, attempts = self.server.transport.read(self.path)
            with body:
                rewritten = rewrite_metadata(body, content_type, self.path,
                                             self.server.base, self.server.transport.cache)
                if rewritten is None:
                    body.seek(0, os.SEEK_END)
                    length = body.tell()
                    body.seek(0)
                else:
                    length = len(rewritten)
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(length))
                self.send_header('X-Homelab-Source', source)
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                if rewritten is None:
                    shutil.copyfileobj(body, self.wfile, length=1024 * 1024)
                else:
                    self.wfile.write(rewritten)
                with self.server.receipt_lock:
                    with self.server.receipts.open('a') as receipts:
                        receipts.write(json.dumps({'route': self.path, 'source': source,
                                                   'attempts': attempts, 'bytes': length}) + '\n')
        except (BrokenPipeError, ConnectionResetError):
            return
        except ValueError:
            self.send_error(400, 'Unreviewed dependency request')
        except urllib.error.HTTPError as error:
            self.send_error(error.code, 'Dependency origin rejected request')
        except RuntimeError:
            self.send_error(502, 'Dependency transport exhausted bounded attempts')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=18082)
    parser.add_argument('--receipts', type=Path, required=True)
    args = parser.parse_args()
    os.umask(0o077)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.transport = Transport()
    server.base = 'http://127.0.0.1:' + str(args.port)
    server.receipts = args.receipts
    server.receipt_lock = threading.Lock()
    server.serve_forever()


if __name__ == '__main__':
    main()
