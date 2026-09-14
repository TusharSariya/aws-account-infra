"""Challenge the currently listening source before trusting its process identity."""
import hashlib
import hmac
import ipaddress
import json
import re
import secrets
import urllib.request

from kube import Unavailable


PORTS = {'ollama': 11434, 'odysseus': 7001}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def probe(address, source, key):
    if not key:
        raise Unavailable('Activity identity credential unavailable')
    host = ipaddress.ip_address(address)
    authority = '[' + str(host) + ']' if host.version == 6 else str(host)
    port = PORTS[source]
    challenge = secrets.token_hex(16)
    request = urllib.request.Request(f'http://{authority}:{port}/activity-identity?challenge={challenge}',
        headers={'Authorization': 'Bearer ' + key})
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect)
        with opener.open(request, timeout=2) as response:
            payload = json.loads(response.read(8193))
        process = payload['process_id']
        signature = payload['signature']
        if not isinstance(process, str) or not re.fullmatch('[a-f0-9]{32}', process):
            raise ValueError()
        expected = hmac.new(key.encode(), (challenge + ':' + process).encode(), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
            raise ValueError()
        return process
    except (OSError, ValueError, KeyError, TypeError):
        raise Unavailable('Current activity process identity is unverified') from None
