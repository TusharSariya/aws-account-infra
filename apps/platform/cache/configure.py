"""Reconcile reviewed Nexus CE repositories and least-privilege roles via REST."""
import base64
import json
import os
from pathlib import Path
import urllib.error
import urllib.request

BASE = 'http://nexus.homelab-cache.svc.cluster.local:8081/service/rest/v1/'


def request(path, method='GET', value=None, password=None, text=False):
    password = password or Path('/credentials/admin-password').read_text().strip()
    headers = {'Authorization': 'Basic ' + base64.b64encode(('admin:'+password).encode()).decode()}
    data = None
    if value is not None:
        headers['Content-Type'] = 'text/plain' if text else 'application/json'
        data = value.encode() if text else json.dumps(value).encode()
    req = urllib.request.Request(BASE+path, headers=headers, data=data, method=method)
    # Never follow redirects with administrative credentials.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args): return None
    with urllib.request.build_opener(NoRedirect()).open(req, timeout=60) as response:
        body = response.read()
        return json.loads(body) if body else None


def reconcile():
    config = json.loads(Path('/config/repositories.json').read_text())
    try:
        request('security/users?userId=admin')
    except urllib.error.HTTPError as error:
        if error.code != 401: raise
        initial = Path('/bootstrap/admin.password').read_text().strip()
        request('security/users/admin/change-password', 'PUT',
                Path('/credentials/admin-password').read_text().strip(), password=initial, text=True)
    if config['acceptEula'] is not True:
        raise ValueError('Explicit EULA authorization required')
    eula = request('system/eula')
    if not eula['accepted']:
        request('system/eula', 'POST', {'accepted': True, 'disclaimer': eula['disclaimer']})
    # All managed repositories share the XFS-bounded content store.
    blob = request('blobstores/file/default')
    blob['softQuota'] = {'type':'spaceUsedQuota', 'limit': int(48 * 1024**3 * .8)}
    request('blobstores/file/default','PUT',blob)
    existing = {r['name']: r for r in request('repositories')}
    read = []
    for repo in config['repositories']:
        name, fmt, kind = repo['name'], repo['format'], repo['type']
        body = {'name': name, 'online': True,
                'storage': {'blobStoreName': 'default', 'strictContentTypeValidation': True}}
        if kind == 'proxy':
            body.update(proxy={'remoteUrl':repo['remote'], 'contentMaxAge':1440, 'metadataMaxAge':60},
                        negativeCache={'enabled':True,'timeToLive':5},
                        httpClient={'blocked':False,'autoBlock':True,
                                    'connection':{'retries':2,'timeout':30,'enableCircularRedirects':False,'enableCookies':False}})
        else:
            body['storage']['writePolicy'] = 'ALLOW'
        if fmt == 'apt': body['apt'] = {'distribution':repo['distribution'], 'flat':False}
        if fmt == 'docker':
            body['docker']={'v1Enabled':False,'forceBasicAuth':kind=='hosted','httpPort':repo['port']}
            if kind=='proxy': body['dockerProxy']={'indexType': 'HUB' if name=='docker-hub' else 'REGISTRY', 'cacheForeignLayers':False}
        endpoint = f'repositories/{fmt}/{kind}'
        if name in existing:
            if (existing[name]['format'], existing[name]['type']) != (fmt,kind):
                raise ValueError('Repository identity differs: '+name)
            observed=request(endpoint+'/'+name)
            # CE cleanup is intentionally managed in the supported UI. Preserve it.
            if observed.get('cleanup'):body['cleanup']=observed['cleanup']
            request(endpoint+'/'+name,'PUT',body)
        else: request(endpoint,'POST',body)
        read.extend(f'nx-repository-view-{fmt}-{name}-{action}' for action in ('browse','read'))
    roles={r['id'] for r in request('security/roles')}
    writer=[f'nx-repository-view-docker-docker-build-{action}' for action in ('browse','read','add','edit')]
    privileges = {p['name'] for p in request('security/privileges')}
    if 'cache-metrics-read' not in privileges:
        request('security/privileges/wildcard', 'POST', {'name': 'cache-metrics-read',
                'description': 'Read CE usage metrics', 'pattern': 'nexus:metrics:read'})
    for identity, privileges in [('cache-reader',read),('cache-build-writer',writer),
                                 ('cache-monitor', ['cache-metrics-read'])]:
        body={'id':identity,'name':identity,'description':'Local disposable cache access','privileges':privileges,'roles':[]}
        request('security/roles'+('/'+identity if identity in roles else ''),'PUT' if identity in roles else 'POST',body)
    users={u['userId']:u for u in request('security/users')}
    for identity,role in [('anonymous','cache-reader'),('cache-build-writer','cache-build-writer'),('cache-monitor','cache-monitor')]:
        body={'userId':identity,'firstName':'Cache','lastName':identity,'email':'cache@localhost.invalid','status':'active','roles':[role]}
        if identity in users:request('security/users/'+identity,'PUT',body)
        else:
            body['password']=Path('/credentials/' + ('metrics-password' if identity == 'cache-monitor' else 'build-password')).read_text().strip()
            request('security/users','POST',body)
    request('security/anonymous','PUT',{'enabled':True,'userId':'anonymous','realmName':'NexusAuthorizingRealm'})
    realms=request('security/realms/active')
    if 'DockerToken' not in realms:request('security/realms/active','PUT',realms+['DockerToken'])
    print('PASS: authorized EULA, repository definitions and least-privilege roles reconciled; verify UI cleanup before routing')


if __name__ == '__main__':
    try: reconcile()
    except Exception as error:
        # Response bodies may include input credentials. Do not log them.
        print('Nexus reconciliation failed: '+type(error).__name__, flush=True)
        raise SystemExit(1) from None
