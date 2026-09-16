"""Fetch checksum-pinned tools with bounded cache/upstream attempts and atomic output."""
import argparse
import hashlib
import http.client
import os
from pathlib import Path
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request

CACHE = 'http://nexus.homelab-cache.svc.cluster.local:8081/repository/'
ORIGINS = {
    'github.com': 'raw-github',
    'codeload.github.com': 'raw-codeload',
    'awscli.amazonaws.com': 'raw-awscli',
    'dl.k8s.io': 'raw-kubernetes',
    'get.helm.sh': 'raw-helm',
    'go.dev': 'raw-go',
}


class IntegrityError(ValueError):
    pass


class Redirects(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Cache redirects must not silently spend upstream attempts. Upstream
        # redirects retain HTTPS verification and carry no credentials.
        if req.full_url.startswith(CACHE) or urllib.parse.urlsplit(newurl).scheme != 'https':
            raise urllib.error.HTTPError(req.full_url, code, 'Redirect rejected', headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def cache_url(url):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port or parsed.fragment:
        raise ValueError('Credential-free HTTPS origin required')
    repository = ORIGINS.get(parsed.hostname)
    if repository is None:
        raise ValueError('Review and add the pinned download origin before use')
    path = parsed.path
    if parsed.hostname == 'go.dev':
        if not path.startswith('/dl/'):
            raise ValueError('Only Go release downloads are configured')
        path = path.removeprefix('/dl')
    return CACHE + repository + path + ('?' + parsed.query if parsed.query else '')


def fetch(url, expected_sha256, destination, *, use_cache=False, opener=None):
    if not re.fullmatch(r'[0-9a-f]{64}', expected_sha256):
        raise ValueError('Pinned SHA-256 required')
    cached = cache_url(url)
    opener = opener or urllib.request.build_opener(Redirects())
    destination = Path(destination)
    attempts = ([('cache', cached)] * 2 if use_cache else []) + [('upstream', url)] * 3
    for number, (source, address) in enumerate(attempts, 1):
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=destination.parent, prefix='.download-', delete=False) as output:
                temporary = Path(output.name)
                digest, size = hashlib.sha256(), 0
                with opener.open(address, timeout=30) as response:
                    declared = response.headers.get('Content-Length')
                    while chunk := response.read(1024 * 1024):
                        digest.update(chunk)
                        size += len(chunk)
                        output.write(chunk)
                    if declared is not None and size != int(declared):
                        raise http.client.IncompleteRead(b'', int(declared) - size)
                if digest.hexdigest() != expected_sha256:
                    raise IntegrityError('Pinned download checksum mismatch; refusing fallback')
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            return {'source': source, 'attempts': number, 'bytes': size, 'sha256': expected_sha256}
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if number == len(attempts):
                raise RuntimeError('Pinned download failed after bounded attempts') from None
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('url')
    parser.add_argument('sha256')
    parser.add_argument('destination', type=Path)
    parser.add_argument('--cache', action='store_true')
    args = parser.parse_args()
    receipt = fetch(args.url, args.sha256, args.destination, use_cache=args.cache)
    print(f"Verified {receipt['bytes']} bytes via {receipt['source']} after {receipt['attempts']} attempt(s)")
