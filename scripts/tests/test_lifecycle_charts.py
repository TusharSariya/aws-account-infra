import json
from pathlib import Path
import subprocess
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / 'config/environments/kubernetes/homelab'


def render(name):
    args = ['helm', 'template', 'homelab-' + name, str(ROOT / 'charts' / ('homelab-' + name))]
    values = CONFIG / (name + '-values.yaml')
    if values.exists():
        args += ['-f', str(values)]
    return [doc for doc in yaml.safe_load_all(subprocess.check_output(args, text=True)) if doc]


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
        self.assertEqual({v['claimName'] for v in claims}, {'ai-models', 'ai-workspace', 'ai-vector'})
        self.assertTrue(all(v['readOnly'] for v in claims))
        self.assertFalse(any('persistentVolumeClaim' in v for v in restore['volumes']))
        self.assertEqual(next(v['emptyDir'] for v in restore['volumes'] if 'emptyDir' in v)['sizeLimit'], '4Gi')

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
