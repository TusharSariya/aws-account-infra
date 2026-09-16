"""Read-only usage monitoring; publish warnings without expanding storage/licenses."""
import base64
import json
import math
import os
from pathlib import Path
import ssl
import time
import urllib.request

SA = Path('/var/run/secrets/kubernetes.io/serviceaccount')


def evaluate(guest, metrics, volumes, now):
    warnings = []
    for name, volume in volumes.items():
        sample = guest['cache.' + name]
        percent = sample['used_percent']
        if (sample['identity'] != str(volume['project']) or sample['healthy'] is not True
                or not 0 <= now - sample['measured_at'] <= 90
                or not math.isfinite(percent) or not 0 <= percent <= 100):
            raise ValueError('Cache storage telemetry unavailable: ' + name)
        if percent >= 80:
            warnings.append(f'{name} storage at {percent:.1f}%: run supported cleanup and compaction')
    gauges = metrics['gauges']
    usage = {'components': gauges['nexus.analytics.component_total_count']['value'],
             'requests_per_day': gauges['nexus.analytics.content_request_count']['value']['day']}
    for name, threshold in [('components', 30000), ('requests_per_day', 75000)]:
        count = usage[name]
        if type(count) not in (int, float) or not math.isfinite(count) or count < 0:
            raise ValueError('Nexus usage metric unavailable: ' + name)
        if count >= threshold:
            warnings.append(f'{name} at {count}: exceeds 75% CE warning threshold')
    return {'checked_at': now, 'usage': usage, 'warnings': warnings,
            'note': 'Nexus usage gauges can lag; no paid expansion is enabled'}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def fetch(url, headers, method='GET', value=None, context=None):
    if value is not None:
        headers = {**headers, 'Content-Type': 'application/merge-patch+json' if method == 'PATCH' else 'application/json'}
    request = urllib.request.Request(url, headers=headers, method=method,
                                     data=None if value is None else json.dumps(value, allow_nan=False).encode())
    opener = urllib.request.build_opener(NoRedirect(), urllib.request.HTTPSHandler(context=context))
    with opener.open(request, timeout=15) as response:
        return json.load(response)


def main():
    config = json.loads(Path('/config/volumes.json').read_text())
    api = 'https://' + os.environ['KUBERNETES_SERVICE_HOST'] + ':' + os.environ.get('KUBERNETES_SERVICE_PORT_HTTPS', '443')
    tls = ssl.create_default_context(cafile=SA / 'ca.crt')
    def kube(path, method='GET', value=None):
        return fetch(api + '/api/v1/' + path, {'Authorization': 'Bearer ' + (SA / 'token').read_text().strip()}, method, value, tls)
    credentials = 'cache-monitor:' + Path('/credentials/metrics-password').read_text().strip()
    report = None
    try:
        guest = json.loads(kube('namespaces/homelab-platform/configmaps/guest-capacity')['data']['sample.json'])
        metrics = fetch('http://nexus:8081/service/rest/metrics/data',
                        {'Authorization': 'Basic ' + base64.b64encode(credentials.encode()).decode()})
        report = evaluate(guest, metrics, config, time.time())
    except Exception as error:
        report = {'checked_at': time.time(), 'warnings': ['Cache monitoring unavailable: ' + type(error).__name__], 'unavailable': True}
    kube('namespaces/homelab-cache/configmaps/cache-status', 'PATCH', {'data': {'status.json': json.dumps(report)}})
    if report['warnings']:
        kube('namespaces/homelab-cache/events', 'POST', {
            'apiVersion': 'v1', 'kind': 'Event', 'metadata': {'generateName': 'cache-warning-', 'namespace': 'homelab-cache'},
            'involvedObject': {'apiVersion': 'v1', 'kind': 'ConfigMap', 'name': 'cache-status', 'namespace': 'homelab-cache'},
            'type': 'Warning', 'reason': 'CacheCapacity', 'message': '; '.join(report['warnings']),
            'source': {'component': 'cache-monitor'}})
    print(json.dumps(report, allow_nan=False), flush=True)
    if report.get('unavailable'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
