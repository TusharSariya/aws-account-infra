import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/environments/kubernetes/homelab'


def render(name, *sets):
    args = ['helm', 'template', 'homelab-' + name, str(ROOT / 'charts' / ('homelab-' + name))]
    values = CONFIG / (name + '-values.yaml')
    if values.exists():
        args += ['-f', str(values)]
    for value in sets:
        args += ['--set', value]
    return [doc for doc in yaml.safe_load_all(subprocess.check_output(args, text=True)) if doc]


def find(docs, kind, name, namespace=None):
    return next(doc for doc in docs if doc['kind'] == kind and doc['metadata']['name'] == name
                and (namespace is None or doc['metadata'].get('namespace') == namespace))


DESKTOP_OBJECTS = {('StorageClass', None, 'desktop-local-retain'), ('PersistentVolume', None, 'desktop-ollama-models'),
                   ('PersistentVolumeClaim', 'homelab-inference', 'desktop-ollama-models'),
                   ('Deployment', 'homelab-inference', 'desktop-ollama'), ('Service', 'homelab-inference', 'desktop-ollama'),
                   ('NetworkPolicy', 'homelab-inference', 'desktop-ollama'),
                   ('CiliumNetworkPolicy', 'homelab-inference', 'desktop-ollama-internet')}
ROUTER = 'http://playground-router.homelab-models.svc.cluster.local:8080'


class ChartTests(unittest.TestCase):
    def test_backup_has_readonly_sources_and_restore_has_no_production_mounts(self):
        docs = render('ai')
        data = next(doc['data'] for doc in docs if doc['kind'] == 'ConfigMap' and doc['metadata']['name'] == 'ai-maintenance')
        snapshot = json.loads(data['snapshot.json'])['spec']
        restore = json.loads(data['restore.json'])['spec']
        for pod in (snapshot, restore):
            self.assertFalse(pod['automountServiceAccountToken'])
            self.assertFalse(pod['hostUsers'])
            self.assertEqual(pod['activeDeadlineSeconds'], 1800)
            self.assertFalse(any('secret' in v or 'hostPath' in v for v in pod['volumes']))
        claims = [v['persistentVolumeClaim'] for v in snapshot['volumes'] if 'persistentVolumeClaim' in v]
        self.assertEqual({v['claimName'] for v in claims}, {'ai-models', 'ai-workspace', 'ai-vector', 'playground-ui-data', 'playground-router-state'})
        self.assertTrue(all(v['readOnly'] for v in claims))
        self.assertFalse(any('persistentVolumeClaim' in v for v in restore['volumes']))
        self.assertEqual(next(v['emptyDir'] for v in restore['volumes'] if 'emptyDir' in v)['sizeLimit'], '4Gi')

    def test_ui_seeds_a_power_banner_linking_to_the_hold_page(self):
        docs = render('playground')
        ui = next(doc for doc in docs if doc['kind'] == 'Deployment' and doc['metadata']['name'] == 'playground-ui')
        env = {e['name']: e.get('value') for e in ui['spec']['template']['spec']['containers'][0]['env']}
        banners = json.loads(env['WEBUI_BANNERS'])
        self.assertEqual(len(banners), 1)
        self.assertIn('](/_power/)', banners[0]['content'])
        self.assertFalse(banners[0]['dismissible'])

    def test_router_reads_only_its_worker_node_and_kubelet_stats(self):
        docs = render('playground')
        role = next(doc for doc in docs if doc['kind'] == 'ClusterRole' and doc['metadata']['name'] == 'playground-router-node-ready')
        self.assertEqual([(r['resources'], r['resourceNames'], r['verbs']) for r in role['rules']],
                         [(['nodes'], ['talos-worker-01'], ['get']), (['nodes/stats'], ['talos-worker-01'], ['get'])])
        cilium = next(doc for doc in docs if doc['kind'] == 'CiliumNetworkPolicy' and doc['metadata']['name'] == 'playground-router-apiserver')
        self.assertIn({'toEntities': ['host'], 'toPorts': [{'ports': [{'port': '10250', 'protocol': 'TCP'}]}]}, cilium['spec']['egress'])

    def test_desktop_objects_live_only_in_the_desktop_release(self):
        def names(docs):
            return {(d['kind'], d['metadata'].get('namespace'), d['metadata']['name']) for d in docs}
        main, desktop = render('playground'), render('playground', 'desktopOnly=true')
        self.assertEqual(names(desktop), DESKTOP_OBJECTS)
        self.assertFalse(names(main) & names(desktop))
        self.assertFalse(any(d['metadata'].get('namespace') == 'homelab-inference' for d in main))
        self.assertEqual(render('playground', 'desktopOnly=true', 'desktop.enabled=false'), [])
        # The main release still renders router and UI either way.
        self.assertIn(('Deployment', 'homelab-models', 'playground-router'), names(main))
        self.assertIn(('Deployment', 'homelab-models', 'playground-ui'), names(main))

    def test_desktop_release_applies_without_helm_wait(self):
        root = (ROOT / 'live/kubernetes/homelab/playground-desktop.tf').read_text()
        self.assertIn('resource "helm_release" "playground_desktop"', root)
        self.assertIn('desktopOnly   = true', root)
        self.assertIn('wait        = false', root)
        self.assertIn('namespace = "homelab-inference"', root)
        main = (ROOT / 'live/kubernetes/homelab/playground.tf').read_text()
        self.assertNotIn('desktopOnly', main)
        self.assertIn('wait        = true', main)

    def test_desktop_ollama_is_a_kueue_gpu_runtime_tolerating_only_compute(self):
        desktop = render('playground', 'desktopOnly=true')
        deployment = find(desktop, 'Deployment', 'desktop-ollama', 'homelab-inference')
        self.assertEqual(deployment['metadata']['labels']['kueue.x-k8s.io/queue-name'], 'desktop')
        template = deployment['spec']['template']
        self.assertEqual(template['metadata']['labels']['kueue.x-k8s.io/queue-name'], 'desktop')
        pod = template['spec']
        self.assertEqual(pod['runtimeClassName'], 'nvidia')
        self.assertEqual(pod['nodeSelector'], {'kubernetes.io/hostname': 'ubuntu-gpu-01'})
        self.assertEqual(pod['tolerations'], [{'key': 'homelab.tfdraw.dev/compute', 'operator': 'Equal',
                                               'value': 'true', 'effect': 'NoSchedule'}])
        self.assertFalse(any('quarantine' in t['key'] for t in pod['tolerations']))
        self.assertEqual(deployment['spec']['strategy'], {'type': 'Recreate'})
        container = pod['containers'][0]
        self.assertRegex(container['image'], r'@sha256:[a-f0-9]{64}$')
        resources = container['resources']
        self.assertEqual(resources['limits']['nvidia.com/gpu'], 1)
        self.assertEqual(resources['requests']['memory'], resources['limits']['memory'])
        env = {e['name']: e['value'] for e in container['env']}
        self.assertEqual((env['OLLAMA_KV_CACHE_TYPE'], env['OLLAMA_FLASH_ATTENTION'], env['OLLAMA_MAX_LOADED_MODELS']),
                         ('q8_0', '1', '1'))
        self.assertTrue(container['securityContext']['readOnlyRootFilesystem'])
        volume = find(desktop, 'PersistentVolume', 'desktop-ollama-models')
        self.assertEqual(volume['spec']['persistentVolumeReclaimPolicy'], 'Retain')
        self.assertEqual(volume['spec']['claimRef'], {'namespace': 'homelab-inference', 'name': 'desktop-ollama-models'})

    def test_only_the_router_reaches_desktop_ollama(self):
        docs = render('playground')
        policy = find(render('playground', 'desktopOnly=true'), 'NetworkPolicy', 'desktop-ollama', 'homelab-inference')
        self.assertEqual(policy['spec']['ingress'], [{
            'from': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'homelab-models'}},
                      'podSelector': {'matchLabels': {'app': 'playground-router'}}}],
            'ports': [{'protocol': 'TCP', 'port': 11434}]}])
        rule = {'to': [{'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': 'homelab-inference'}},
                        'podSelector': {'matchLabels': {'app': 'desktop-ollama'}}}],
                'ports': [{'protocol': 'TCP', 'port': 11434}]}
        self.assertIn(rule, find(docs, 'NetworkPolicy', 'playground-router')['spec']['egress'])
        off = find(render('playground', 'desktop.enabled=false'), 'NetworkPolicy', 'playground-router')
        self.assertNotIn(rule, off['spec']['egress'])

    def test_router_config_gains_the_manual_power_desktop_backend_only_when_enabled(self):
        def config(docs):
            return json.loads(find(docs, 'ConfigMap', 'playground-router-config')['data']['config.json'])
        on, off = config(render('playground')), config(render('playground', 'desktop.enabled=false'))
        self.assertEqual([b['name'] for b in on['backends']], ['server', 'desktop'])
        self.assertEqual([b['name'] for b in off['backends']], ['server'])
        desktop = on['backends'][1]
        self.assertTrue(desktop['manual_power'])
        self.assertEqual(desktop['url'], 'http://desktop-ollama.homelab-inference.svc.cluster.local:11434')
        self.assertEqual(desktop['kv_type'], 'q8_0')
        for key in ('token_file', 'node', 'namespace', 'runtime_selector'):
            self.assertNotIn(key, desktop)

    def test_ui_has_one_prefixed_connection_per_backend(self):
        def env(docs):
            ui = find(docs, 'Deployment', 'playground-ui')
            return {e['name']: e for e in ui['spec']['template']['spec']['containers'][0]['env']}
        on, off = env(render('playground')), env(render('playground', 'desktop.enabled=false'))
        self.assertEqual(on['OLLAMA_BASE_URLS']['value'], ROUTER + '/b/server;' + ROUTER + '/b/desktop')
        self.assertEqual(off['OLLAMA_BASE_URLS']['value'], ROUTER + '/b/server')
        self.assertNotIn('OLLAMA_BASE_URL', on)
        configs = json.loads(on['OLLAMA_API_CONFIGS']['value'])
        self.assertEqual({k: (v['enable'], v['prefix_id']) for k, v in configs.items()},
                         {'0': (True, 'server'), '1': (True, 'desktop')})
        # The bearer never lands in values: Kubernetes expands it from the bootstrap-managed Secret.
        self.assertTrue(all(v['key'] == '$(PLAYGROUND_ROUTER_TOKEN)' for v in configs.values()))
        self.assertEqual(on['PLAYGROUND_ROUTER_TOKEN']['valueFrom'],
                         {'secretKeyRef': {'name': 'playground-router-auth', 'key': 'token'}})
        names = list(on)
        self.assertLess(names.index('PLAYGROUND_ROUTER_TOKEN'), names.index('OLLAMA_API_CONFIGS'))

    def test_owner_hold_lease_is_configured_and_readable(self):
        docs = render('lifecycle')
        config = json.loads(next(doc for doc in docs if doc['kind'] == 'ConfigMap'
                                 and doc['metadata']['name'] == 'ai-lifecycle-config')['data']['config.json'])
        self.assertEqual(config['holdLease'], 'host-hold-playground')
        role = next(doc for doc in docs if doc['kind'] == 'Role' and doc['metadata']['name'] == 'ai-lifecycle'
                    and doc['metadata']['namespace'] == 'homelab-platform')
        self.assertIn({'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'],
                       'resourceNames': ['host-hold-playground'], 'verbs': ['get']}, role['rules'])

    def test_reviewed_idle_timeout_reaches_controller_configuration(self):
        docs = render('lifecycle')
        config = next(doc for doc in docs if doc['kind'] == 'ConfigMap' and doc['metadata']['name'] == 'ai-lifecycle-config')
        rendered = json.loads(config['data']['config.json'])
        self.assertEqual(rendered['idleTimeoutSeconds'], 300)
        defaults = yaml.safe_load((ROOT / 'charts/homelab-lifecycle/values.yaml').read_text())
        self.assertEqual(defaults['config']['idleTimeoutSeconds'], 1800)
        # The control plane is a 2 vCPU guest; the reviewed cadence is 10 s, not 2 s.
        self.assertEqual(rendered['tickSeconds'], 10)
        self.assertEqual(defaults['config']['tickSeconds'], 10)

    def test_controller_owns_only_runtime_and_has_no_secret_or_host_access(self):
        docs = render('lifecycle')
        deployment = next(doc for doc in docs if doc['kind'] == 'Deployment')
        pod = deployment['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertFalse(any('hostPath' in volume for volume in pod['volumes']))
        self.assertFalse(pod.get('hostPID', False))
        for doc in docs:
            if doc['kind'] == 'Role':
                for rule in doc['rules']:
                    self.assertFalse(set(rule['resources']) & {'secrets', 'nodes', 'pods/exec', '*'})
                    if 'deployments' in rule['resources'] and 'create' not in rule['verbs']:
                        self.assertEqual(rule['resourceNames'], ['ai-runtime'])
        policy = next(doc for doc in docs if doc['kind'] == 'ValidatingAdmissionPolicy')
        self.assertIn("object.metadata.name == 'ai-runtime'", policy['spec']['validations'][0]['expression'])
        self.assertEqual(policy['spec']['failurePolicy'], 'Fail')

    def test_json_template_matches_yaml_and_gateway_has_no_raw_listener(self):
        docs = render('ai')
        data = next(doc['data'] for doc in docs if doc['kind'] == 'ConfigMap' and doc['metadata']['name'] == 'ai-approved-template')
        self.assertEqual(json.loads(data['deployment.json']), yaml.safe_load(data['deployment.yaml']))
        pod = json.loads(data['deployment.json'])['spec']['template']['spec']
        model, workspace = pod['containers'][:2]
        env = {item['name']: item.get('value') for item in model['env']}
        self.assertEqual(env['OLLAMA_HOST'], '0.0.0.0:11434')
        self.assertEqual(model['readinessProbe']['httpGet']['path'], '/healthz')
        credentials = {volume['name']: volume['secret'] for volume in pod['volumes'] if 'secret' in volume}
        self.assertEqual({item['key'] for item in credentials['workspace-credentials']['items']}, {'odysseus', 'model-workspace'})
        self.assertNotIn('operator', str(credentials))
        self.assertNotIn('11435', str(pod))
        for container in (model, workspace):
            self.assertIn({'name': 'POD_UID', 'valueFrom': {'fieldRef': {'fieldPath': 'metadata.uid'}}}, container['env'])

    def test_reviewed_jobs_have_scoped_accounts_and_shared_schedule_mutex(self):
        docs = render('jobs')
        accounts = {doc['metadata']['name']: doc for doc in docs if doc['kind'] == 'ServiceAccount'}
        self.assertTrue(accounts['homelab-job']['automountServiceAccountToken'])
        self.assertTrue(accounts['ai-operator-job']['automountServiceAccountToken'])
        self.assertFalse(accounts['homelab-workflow-client']['automountServiceAccountToken'])
        templates = {doc['metadata']['name']: doc['spec'] for doc in docs if doc['kind'] == 'WorkflowTemplate'}
        self.assertEqual(set(templates), {'ai-start', 'ai-stop', 'ai-force-stop', 'ai-status', 'smoke', 'independent-smoke'})
        for name, spec in templates.items():
            injected = json.loads(spec['podSpecPatch'])['volumes']
            self.assertEqual({v['name']: v['emptyDir']['sizeLimit'] for v in injected},
                             {'var-run-argo': '192Mi', 'tmp-dir-argo': '16Mi'})
            operation = name.startswith('ai-')
            self.assertEqual(spec['serviceAccountName'], 'ai-operator-job' if operation else 'homelab-job')
            self.assertFalse(any('hostPath' in volume for volume in spec['volumes']))
            self.assertEqual(any('secret' in volume for volume in spec['volumes']), operation)
            if not operation:
                self.assertEqual(spec['synchronization']['mutexes'], [{'name': name}])
            else:
                self.assertNotIn('synchronization', spec)
        cron = next(doc['spec'] for doc in docs if doc['kind'] == 'CronWorkflow')
        self.assertEqual(cron['workflowSpec']['workflowTemplateRef']['name'], 'smoke')
        self.assertEqual(cron['timezone'], 'UTC')
        self.assertEqual(cron['concurrencyPolicy'], 'Forbid')
        self.assertTrue(cron['suspend'])
        result_role = next(doc for doc in docs if doc['kind'] == 'Role' and doc['metadata']['name'] == 'homelab-job-result')
        self.assertEqual(result_role['rules'], [{'apiGroups': ['argoproj.io'], 'resources': ['workflowtaskresults'], 'verbs': ['create', 'patch']}])

    def test_admission_explicitly_denies_every_other_pinned_workflow_spec_field(self):
        docs = render('jobs')
        policy = next(doc for doc in docs if doc['kind'] == 'ValidatingAdmissionPolicy')
        fields = json.loads((ROOT / 'apps/platform/jobs/workflow-schema.lock.json').read_text())['fields']
        expression = policy['spec']['validations'][1]['expression']
        for name in set(fields) - {'workflowTemplateRef', 'arguments', 'shutdown', 'suspend'}:
            self.assertIn('!has(object.spec.' + name + ')', expression)
        binding = next(doc for doc in docs if doc['kind'] == 'ValidatingAdmissionPolicyBinding')
        self.assertEqual(binding['spec']['validationActions'], ['Deny'])

    def test_argo_is_pinned_client_authenticated_and_namespace_scoped(self):
        chart = ROOT / 'live/kubernetes/homelab/.terraform/argo-workflows-2.0.5.tgz'
        rendered = subprocess.check_output(['helm', 'template', 'argo-workflows', str(chart), '-n', 'homelab-jobs',
                                           '-f', str(CONFIG / 'argo-values.yaml')], text=True)
        docs = [doc for doc in yaml.safe_load_all(rendered) if doc]
        for doc in docs:
            if doc['kind'] in ('ClusterRole', 'ClusterRoleBinding'):
                self.assertEqual(doc['metadata']['name'], 'argo-workflows-crd-install')
                self.assertIn('hook-succeeded', doc['metadata']['annotations']['helm.sh/hook-delete-policy'])
            if doc['kind'] == 'Deployment':
                container = doc['spec']['template']['spec']['containers'][0]
                self.assertIn('@sha256:', container['image'])
                self.assertIn('--namespaced', container['args'])
                if doc['metadata']['name'] == 'argo-workflows-server':
                    self.assertIn('--auth-mode=client', container['args'])
