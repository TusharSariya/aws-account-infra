"""Small authenticated API boundary with explicit optimistic concurrency."""
import json
import os
from pathlib import Path
import ssl
import urllib.error
import urllib.request


class Conflict(Exception):
    pass


class Unavailable(Exception):
    pass


class Kubernetes:
    def __init__(self):
        self.credentials = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.context = ssl.create_default_context(cafile=str(self.credentials / 'ca.crt'))
        self.base = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT', '443')

    def call(self, method, path, value=None, optional=False):
        headers = {'Authorization': 'Bearer ' + (self.credentials / 'token').read_text().strip()}
        if value is not None:
            headers['Content-Type'] = 'application/json'
        request = urllib.request.Request(self.base + path,
            data=None if value is None else json.dumps(value).encode(), headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, context=self.context, timeout=3) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code == 404 and optional:
                return None
            if error.code == 409:
                raise Conflict() from None
            raise Unavailable('Kubernetes API rejected the operation') from None
        except (OSError, ValueError):
            raise Unavailable('Kubernetes API unavailable') from None

    def put(self, path, value):
        if not value.get('metadata', {}).get('resourceVersion'):
            raise ValueError('Observed resourceVersion required')
        return self.call('PUT', path + '?fieldValidation=Strict', value)
