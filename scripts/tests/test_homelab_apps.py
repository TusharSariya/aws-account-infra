"""Fail-closed deployment and rendered service contracts; no credentials required."""
import base64
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('apps', ROOT / 'scripts/homelab-apps.py')
apps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(apps)


class GuardTests(unittest.TestCase):
    def plan(self, action):
        return {'resource_changes': [{'address': a, 'change': {'actions': action}} for a in apps.ADDRESSES]}

    def test_safe_plan_and_forbidden_resource_actions(self):
        for actions in [['create'], ['update'], ['no-op']]:
            self.assertEqual(len(apps.guard_plan(self.plan(actions))), len(apps.ADDRESSES))
        for actions in [['delete'], ['delete', 'create'], ['forget']]:
            with self.assertRaises(apps.AppError):
                apps.guard_plan(self.plan(actions))
        invalid = self.plan(['create'])
        invalid['resource_changes'][0]['address'] = 'talos_machine_bootstrap.cluster'
        with self.assertRaises(apps.AppError):
            apps.guard_plan(invalid)
        with self.assertRaises(apps.AppError):
            apps.guard_plan({'resource_changes': []})

    def test_missing_credentials_prevent_any_cluster_mutation(self):
        with patch.dict(apps.os.environ, {'GITHUB_ACTIONS': 'true', **dict.fromkeys(apps.SECRET_NAMES, '')}), patch.object(apps, 'run') as run:
            with self.assertRaises(apps.AppError):
                apps.bootstrap('kubectl')
            run.assert_not_called()

    def test_changed_saved_plan_cannot_apply(self):
        with tempfile.TemporaryDirectory() as d, patch.dict(apps.os.environ, {'GITHUB_ACTIONS': 'true'}), patch.object(apps, 'run') as run, patch.object(apps, 'guard_images'), patch.object(apps, 'credentials'):
            p = Path(d)
            (p / 'apps.tfplan').write_bytes(b'changed')
            (p / 'apps-plan.sha256').write_text('previous')
            with self.assertRaises(apps.AppError):
                apps.execute('apply', p)
            run.assert_not_called()

    def test_raw_and_encoded_credentials_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)
            (p / 'kubeconfig').write_text('users: []\n')
            with patch.dict(apps.os.environ, {'PIHOLE_ADMIN_PASSWORD': 'fixture-password-only'}):
                for value in ['fixture-password-only', base64.b64encode(b'fixture-password-only').decode()]:
                    with self.assertRaises(apps.AppError):
                        apps.check_secrets(json.dumps({'value': value}).encode(), p)

    def test_private_https_bypasses_os_dns_without_disabling_tls(self):
        with patch.object(apps, 'run', side_effect=[json.dumps({'Peer': {'peer': {'DNSName': 'pve.tail2f646b.ts.net.', 'TailscaleIPs': ['100.101.182.9']}}}).encode(), b'401']) as run:
            apps.tailnet_https('pve.tail2f646b.ts.net', '/api2/json/version', ['-w', '%{http_code}'])
        self.assertEqual(run.call_args_list[0].args[0], ['tailscale', 'status', '--json'])
        curl = run.call_args_list[1].args[0]
        self.assertIn('--resolve', curl)
        self.assertIn('pve.tail2f646b.ts.net:443:100.101.182.9', curl)
        self.assertNotIn('--insecure', curl)
        self.assertIn('https://pve.tail2f646b.ts.net/api2/json/version', curl)

    def test_private_resolution_rejects_public_or_multiple_addresses(self):
        for addresses in [['1.1.1.1'], ['100.101.182.9', '100.101.182.10']]:
            status = {'Peer': {'peer': {'DNSName': 'pve.tail2f646b.ts.net.', 'TailscaleIPs': addresses}}}
            with patch.object(apps, 'run', return_value=json.dumps(status).encode()), self.assertRaises(apps.AppError):
                apps.tailnet_ip('pve.tail2f646b.ts.net')

    def test_private_resolution_waits_for_new_peer_and_matches_exact_dns_name(self):
        unrelated = {'Peer': {'other': {'DNSName': 'other.tail2f646b.ts.net.', 'TailscaleIPs': ['100.100.100.1']}}}
        ready = {'Peer': {'new': {'DNSName': 'pihole-admin.tail2f646b.ts.net.', 'TailscaleIPs': ['100.81.38.51', 'fd7a:115c:a1e0::1']}}}
        with patch.object(apps, 'run', side_effect=[json.dumps(unrelated).encode(), json.dumps(ready).encode()]), \
             patch('time.sleep') as sleep:
            self.assertEqual(apps.tailnet_ip('pihole-admin.tail2f646b.ts.net'), '100.81.38.51')
            sleep.assert_called_once()
        with patch.object(apps, 'run', return_value=b'{"Peer": {}}'), patch('time.sleep'), self.assertRaises(apps.AppError):
            apps.tailnet_ip('pihole-admin.tail2f646b.ts.net')

    def test_clusterip_endpoint_checks_use_proxy_readiness_and_tailnet_map(self):
        def command(argv):
            if argv[0] == 'dig':
                return b'0.0.0.0' if 'doubleclick.net' in argv else b'93.184.215.14'
            if 'get' in argv:
                return b'{}'  # ClusterIP services have no loadBalancer.ingress.
            return b''
        with patch.object(apps, 'run', side_effect=command) as run, \
             patch.object(apps, 'tailnet_ip', return_value='100.101.182.10') as resolve, \
             patch.object(apps, 'tailnet_https', side_effect=[b'OK', b'401', b'{"version":"test"}', b'OK', b'401']):
            apps.endpoints('kubectl')
        resolve.assert_called_once_with('pihole-dns.tail2f646b.ts.net')
        waits = [call.args[0] for call in run.call_args_list if 'wait' in call.args[0]]
        dns_wait = next(argv for argv in waits if 'service/pihole-dns' in argv)
        self.assertIn('--for=condition=TailscaleProxyReady=true', dns_wait)

    def test_command_timeout_allows_helm_to_finish_and_release_state_lock(self):
        with patch.object(apps.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b''
            apps.run(['tofu', 'apply'])
            self.assertGreater(run.call_args.kwargs['timeout'], 900 + 60)

    def test_child_environment_excludes_credentials(self):
        with patch.dict(apps.os.environ, dict.fromkeys(apps.SECRET_NAMES, 'fixture')), patch.object(apps.subprocess, 'run') as run:
            run.return_value.returncode = 0
            run.return_value.stdout = b''
            apps.run(['command'])
            for name in apps.SECRET_NAMES:
                self.assertNotIn(name, run.call_args.kwargs['env'])

    def test_image_guard_rejects_mutable_tags_before_planning(self):
        with tempfile.TemporaryDirectory() as d, patch.object(apps, 'CONFIG', Path(d)), patch.object(apps, 'run') as run:
            config = Path(d)
            (config / 'ollama-values.yaml').write_text('image: ollama/ollama:latest')
            (config / 'workspace-values.yaml').write_text('image: test\ninitImage: test\ncomponents: {}')
            with self.assertRaises(apps.AppError):
                apps.execute('plan', config)
            run.assert_not_called()

    def test_failure_diagnostics_emit_only_fixed_categories(self):
        import contextlib
        import io
        diagnostics = io.StringIO()
        with patch.object(apps.subprocess, 'run') as run, contextlib.redirect_stderr(diagnostics):
            run.return_value.returncode = 1
            run.return_value.stderr = b'openapi timeout PRIVATE-FIXTURE-CONTENT'
            with self.assertRaises(apps.AppError):
                apps.run(['tofu', 'apply'])
        self.assertIn('schema-discovery,timeout', diagnostics.getvalue())
        self.assertNotIn('PRIVATE-FIXTURE-CONTENT', diagnostics.getvalue())

    def test_credential_update_preserves_metadata_and_cas_without_schema_discovery(self):
        current = {'apiVersion': 'v1', 'kind': 'Secret', 'type': 'Opaque', 'data': {'password': 'old'},
                   'metadata': {'name': 'pihole-admin', 'namespace': 'homelab-services',
                                'resourceVersion': '17', 'labels': {'preserve': 'true'}}}
        desired = {**current, 'metadata': {'name': 'pihole-admin', 'namespace': 'homelab-services'},
                   'data': {'password': 'new'}}
        with patch.object(apps, 'run', side_effect=[json.dumps(current).encode(), b'']) as run:
            apps.reconcile_credential_object('kubectl', desired)
        command, payload = run.call_args.args
        self.assertIn('replace', command)
        self.assertIn('/api/v1/namespaces/homelab-services/secrets/pihole-admin?fieldValidation=Strict&fieldManager=homelab-app-credentials', command)
        result = json.loads(payload)
        self.assertEqual(result['metadata']['resourceVersion'], '17')
        self.assertEqual(result['metadata']['labels'], {'preserve': 'true'})
        self.assertNotIn('kubectl.kubernetes.io/last-applied-configuration', result['metadata'].get('annotations', {}))
        self.assertEqual(result['data'], {'password': 'new'})
        with patch.object(apps, 'run') as run, self.assertRaises(apps.AppError):
            apps.reconcile_credential_object('kubectl', {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'unrelated', 'namespace': 'default'}})
        run.assert_not_called()

    def test_new_credentials_are_external_and_registry_secret_has_correct_type(self):
        values = dict.fromkeys(apps.SECRET_NAMES, 'a-fixture-only-value-that-is-long-enough')
        with patch.dict(apps.os.environ, {**values, 'GITHUB_ACTIONS': 'true'}), patch.object(apps, 'run', return_value=b'') as run:
            apps.bootstrap('kubectl')
        manifests = [json.loads(call.args[1]) for call in run.call_args_list if len(call.args) == 2]
        registry = next(m for m in manifests if m['metadata']['name'] == 'ghcr-read')
        self.assertEqual(registry['type'], 'kubernetes.io/dockerconfigjson')
        config = json.loads(base64.b64decode(registry['data']['.dockerconfigjson']))
        self.assertEqual(base64.b64decode(config['auths']['ghcr.io']['auth']).decode(), values['GHCR_READ_USER'] + ':' + values['GHCR_READ_TOKEN'])
        self.assertFalse(any('stringData' in m for m in manifests))
        for missing in ['GHCR_READ_TOKEN', 'ODYSSEUS_ADMIN_PASSWORD', 'SEARXNG_SECRET']:
            with patch.dict(apps.os.environ, {**values, 'GITHUB_ACTIONS': 'true', missing: ''}), patch.object(apps, 'run') as run:
                with self.assertRaises(apps.AppError):
                    apps.bootstrap('kubectl')
                run.assert_not_called()



class ChartTests(unittest.TestCase):
    def render(self, name, version, namespace, values):
        data = subprocess.check_output(['helm', 'template', name,
            str(apps.TF / '.terraform' / f'{name}-{version}.tgz'), '-n', namespace,
            '-f', str(apps.CONFIG / values)], text=True)
        return [x for x in yaml.safe_load_all(data) if x]

    def test_pihole_ports_storage_auth_and_update_contract(self):
        docs = self.render('pihole', '2.38.0', 'homelab-services', 'pihole-values.yaml')
        by_kind = {}
        for doc in docs:
            by_kind.setdefault(doc['kind'], []).append(doc)
        self.assertNotIn('Secret', by_kind)
        deployment = by_kind['Deployment'][0]['spec']
        self.assertEqual(deployment['replicas'], 1)
        self.assertEqual(deployment['strategy']['type'], 'Recreate')
        pod = deployment['template']['spec']
        self.assertEqual(pod['dnsPolicy'], 'None')
        self.assertEqual(pod['dnsConfig']['nameservers'], ['1.1.1.1', '1.0.0.1'])
        self.assertFalse(pod['hostNetwork'])
        container = pod['containers'][0]
        self.assertIn('@sha256:', container['image'])
        env = {x['name']: x for x in container['env']}
        self.assertEqual(env['FTLCONF_webserver_api_password']['valueFrom']['secretKeyRef']['name'], 'pihole-admin')
        self.assertEqual(env['FTLCONF_database_maxDBdays']['value'], '7')
        services = by_kind['Service']
        self.assertTrue(all(x['spec']['type'] == 'ClusterIP' for x in services))
        dns = next(x for x in services if x['metadata']['name'] == 'pihole-dns')
        self.assertEqual({(x['port'], x['protocol']) for x in dns['spec']['ports']}, {(53, 'TCP'), (53, 'UDP')})
        self.assertEqual(dns['metadata']['annotations']['tailscale.com/expose'], 'true')
        self.assertFalse(any(p['port'] == 67 for s in services for p in s['spec']['ports']))
        pvc = by_kind['PersistentVolumeClaim'][0]
        self.assertEqual(pvc['spec']['storageClassName'], 'worker-local-retain')
        self.assertEqual(pvc['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
        ingress = by_kind['Ingress'][0]
        self.assertEqual(ingress['spec']['ingressClassName'], 'tailscale')
        for rule in ingress['spec']['rules']:
            self.assertIn(rule.get('host', ''), ['', ingress['spec']['tls'][0]['hosts'][0]])
        self.assertNotIn('tailscale.com/funnel', ingress['metadata'].get('annotations', {}))

    def test_operator_uses_external_secret_and_pinned_images(self):
        docs = self.render('tailscale-operator', '1.102.3', 'tailscale', 'operator-values.yaml')
        self.assertFalse(any(d['kind'] == 'Secret' for d in docs))
        dep = next(d for d in docs if d['kind'] == 'Deployment')
        pod = dep['spec']['template']['spec']
        self.assertTrue(any(v.get('secret', {}).get('secretName') == 'operator-oauth' for v in pod['volumes']))
        self.assertIn('@sha256:', pod['containers'][0]['image'])

    def test_workspace_isolation_persistence_and_sequential_cpu_budget(self):
        docs = []
        for name, values in [('ollama', 'ollama'), ('odysseus', 'workspace')]:
            rendered = subprocess.check_output(['helm', 'template', name, str(ROOT / 'charts' / ('homelab-' + name)),
                '-n', 'homelab-models', '-f', str(apps.CONFIG / (values + '-values.yaml'))], text=True)
            docs.extend(d for d in yaml.safe_load_all(rendered) if d)
        self.assertFalse(any(d['kind'] in ['Secret', 'ClusterRole', 'ClusterRoleBinding'] for d in docs))
        claims = [d for d in docs if d['kind'] == 'PersistentVolumeClaim']
        self.assertEqual({d['metadata']['name'] for d in claims}, {'ollama-models', 'odysseus-data', 'chromadb-data'})
        self.assertEqual(sum(int(d['spec']['resources']['requests']['storage'][:-2]) for d in claims), 330)
        for claim in claims:
            self.assertEqual(claim['metadata']['annotations']['helm.sh/resource-policy'], 'keep')
            self.assertEqual(claim['spec']['storageClassName'], 'worker-local-retain')
        pods = {}
        for d in docs:
            if d['kind'] == 'Service':
                self.assertEqual(d['spec']['type'], 'ClusterIP')
            if d['kind'] != 'Deployment':
                continue
            self.assertEqual(d['spec']['strategy']['type'], 'Recreate')
            pod = d['spec']['template']['spec']
            pods[d['metadata']['name']] = pod
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertEqual(pod['nodeSelector']['kubernetes.io/hostname'], 'talos-worker-01')
            self.assertTrue(pod['securityContext']['runAsNonRoot'])
            self.assertFalse(pod.get('hostNetwork', False))
            self.assertFalse(any('hostPath' in v for v in pod['volumes']))
            for c in pod['containers'] + pod.get('initContainers', []):
                self.assertFalse(c['securityContext']['allowPrivilegeEscalation'])
                self.assertEqual(c['securityContext']['capabilities']['drop'], ['ALL'])
        ollama = pods['ollama']['containers'][0]
        env = {v['name']: v.get('value') for v in ollama['env']}
        self.assertEqual(env['OLLAMA_MAX_LOADED_MODELS'], '1')
        self.assertEqual(env['OLLAMA_NUM_PARALLEL'], '1')
        self.assertEqual(env['OLLAMA_NO_CLOUD'], 'true')
        self.assertEqual(ollama['resources']['limits']['memory'], '64Gi')
        self.assertTrue(ollama['securityContext']['readOnlyRootFilesystem'])
        self.assertEqual(pods['odysseus']['imagePullSecrets'], [{'name': 'ghcr-read'}])
        env = {v['name']: v for v in pods['odysseus']['containers'][0]['env']}
        self.assertEqual(env['LOCALHOST_BYPASS']['value'], 'false')
        self.assertEqual(env['AUTH_ENABLED']['value'], 'true')
        self.assertIn('secretKeyRef', env['ODYSSEUS_ADMIN_PASSWORD']['valueFrom'])
        ingresses = [d for d in docs if d['kind'] == 'Ingress']
        self.assertEqual({d['metadata']['name'] for d in ingresses}, {'ollama', 'odysseus'})
        for d in ingresses:
            self.assertEqual(d['spec']['ingressClassName'], 'tailscale')
            self.assertNotIn('tailscale.com/funnel', d['metadata'].get('annotations', {}))
            self.assertTrue(all('host' not in r for r in d['spec']['rules']))


if __name__ == '__main__':
    unittest.main()
