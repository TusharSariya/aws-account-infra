"""Exercise rendered admission/runner boundaries and queue failure behavior."""
import importlib.util
import json
import tempfile
import io
import os
from contextlib import redirect_stdout
from tempfile import TemporaryDirectory
from unittest.mock import patch
from pathlib import Path
import subprocess
import sys
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from kueue_capacity import requests


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    result = importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


class Contracts(unittest.TestCase):
    def test_power_gate_uses_the_v1beta2_strategy_and_both_flavors(self):
        docs = self.render('charts/homelab-queue', values='config/environments/kubernetes/homelab-ci/pool-values.yaml')
        queue = next(d for d in docs if d['kind'] == 'ClusterQueue')
        self.assertEqual(queue['apiVersion'], 'kueue.x-k8s.io/v1beta2')
        self.assertNotIn('admissionChecks', queue['spec'])
        self.assertEqual(queue['spec']['admissionChecksStrategy'], {'admissionChecks': [{'name': 'homelab-host-ready'}]})
        self.assertEqual([f['name'] for f in queue['spec']['resourceGroups'][0]['flavors']], ['homelab-worker', 'homelab-secondary'])

    def test_pool_values_select_strict_fifo_and_register_the_operational_gateways(self):
        pool = yaml.safe_load((ROOT/'config/environments/kubernetes/homelab-ci/pool-values.yaml').read_text())
        self.assertEqual(pool['strategy'], 'StrictFIFO')
        gateways = json.loads((ROOT/'platform/automatic-power/gateways.json').read_text())
        chart = yaml.safe_load((ROOT/'charts/homelab-queue/values.yaml').read_text())
        self.assertEqual(sorted(chart['gateways']), sorted(g['name'] for g in gateways if g['namespace'] == 'homelab-models'))
        self.assertEqual(sorted(chart['services']), ['playground-router', 'playground-ui'])
        policy = next(d for d in self.render('charts/homelab-queue', values='config/environments/kubernetes/homelab-ci/pool-values.yaml')
                      if d['kind'] == 'ValidatingAdmissionPolicy')
        operational = next(v['expression'] for v in policy['spec']['variables'] if v['name'] == 'operational')
        for name in chart['gateways'] + chart['services']:
            self.assertIn('"%s"' % name, operational)
        self.assertIn("object.spec.nodeSelector['kubernetes.io/hostname'] == \"talos-worker-01\"", operational)

    def test_playground_gateway_owns_one_durable_hold_lease(self):
        gateways = json.loads((ROOT/'platform/automatic-power/gateways.json').read_text())
        playground = next(g for g in gateways if g['name'] == 'wake-playground')
        self.assertEqual(playground['hold'], {'lease': 'host-hold-playground', 'hosts': 'primary', 'maxSeconds': 43200, 'startsAI': True})
        with tempfile.NamedTemporaryFile('w', suffix='.yaml', delete=False) as f:
            yaml.safe_dump({'gatewayCode': 'pass', 'gateways': gateways}, f)
        docs = self.render('charts/homelab-always-on', values=f.name, namespace='homelab-platform')
        lease = next(d for d in docs if d['kind'] == 'Lease' and d['metadata']['name'] == 'host-hold-playground')
        self.assertEqual(lease['metadata']['namespace'], 'homelab-platform')
        self.assertEqual(lease['metadata']['labels'], {'homelab.tfdraw.dev/power-hold': 'false'})
        self.assertEqual(lease['metadata']['annotations'], {'homelab.tfdraw.dev/hosts': 'primary'})
        role = next(d for d in docs if d['kind'] == 'Role' and d['metadata']['name'] == 'wake-playground-hold')
        self.assertEqual(role['rules'], [{'apiGroups': ['coordination.k8s.io'], 'resources': ['leases'],
                                          'resourceNames': ['host-hold-playground'], 'verbs': ['get', 'patch']}])
        self.assertFalse(any(d['kind'] == 'Role' and d['metadata']['name'] == 'wake-ollama-hold' for d in docs))
        deploy = next(d for d in docs if d['kind'] == 'Deployment' and d['metadata']['name'] == 'wake-playground')
        env = {e['name']: e.get('value') for e in deploy['spec']['template']['spec']['containers'][0]['env']}
        self.assertEqual((env['HOLD_LEASE'], env['HOLD_NAMESPACE'], env['HOLD_MAX_SECONDS'], env['HOLD_STARTS_AI']),
                         ('host-hold-playground', 'homelab-platform', '43200', 'true'))
        pod = deploy['spec']['template']['spec']
        self.assertTrue(any(v.get('secret', {}).get('secretName') == 'wake-lifecycle-auth' for v in pod['volumes']))
        policy = next(d for d in docs if d['kind'] == 'NetworkPolicy' and d['metadata']['name'] == 'wake-playground')
        self.assertTrue(any(any(t.get('podSelector', {}).get('matchLabels', {}).get('app') == 'ai-lifecycle' for t in rule.get('to', []))
                            for rule in policy['spec']['egress']))

    def render(self, chart, name='test', values=None, namespace='default'):
        args = ['helm','template',name,str(ROOT/chart),'--namespace',namespace,'--kube-version','1.36.3']
        if values: args += ['-f',str(ROOT/values)]
        return [d for d in yaml.safe_load_all(subprocess.check_output(args)) if d]

    def test_standalone_queue_has_no_cohort_only_fields(self):
        docs = self.render('charts/homelab-queue')
        queue = next(d for d in docs if d['kind'] == 'ClusterQueue')['spec']
        self.assertNotIn('cohort', queue)
        for quota in queue['resourceGroups'][0]['flavors'][0]['resources']:
            self.assertNotIn('borrowingLimit', quota)
            self.assertNotIn('lendingLimit', quota)
        priority = next(d for d in docs if d['kind'] == 'WorkloadPriorityClass')
        self.assertEqual(priority['value'], 0)
        self.assertNotIn('globalDefault', priority)

    def test_runner_entire_pod_resources_and_no_host_mounts(self):
        documents = self.render('live/kubernetes/homelab-management/.terraform/gha-runner-scale-set-0.14.2.tgz',
            name='homelab-talos',namespace='arc-runners',values='config/environments/kubernetes/homelab-ci/arc-runner-values.yaml')
        scale = next(d for d in documents if d['kind'] == 'AutoscalingRunnerSet')['spec']
        self.assertEqual(scale['minRunners'], 0)
        self.assertNotIn('maxRunners', scale)
        self.assertEqual(scale['githubConfigSecret'],'github-app')
        pod = scale['template']
        self.assertEqual(requests(pod,'cpu'),4)
        self.assertEqual(requests(pod,'memory'),16*1024**3)
        self.assertEqual(pod['metadata']['labels']['kueue.x-k8s.io/queue-name'],'ci')
        for c in pod['spec']['containers']+pod['spec']['initContainers']:
            self.assertEqual(c['resources']['requests'],c['resources']['limits'])
            self.assertIn('@sha256:',c['image'])
        docker = next(c for c in pod['spec']['initContainers'] if c['name']=='dind')
        self.assertIn('mount -t binfmt_misc', docker['args'][0])
        self.assertIn('exec dockerd-entrypoint.sh dockerd', docker['args'][0])
        self.assertTrue(all('hostPath' not in v for v in pod['spec']['volumes']))
        self.assertEqual(pod['spec']['volumes'],[dict(name='scratch',emptyDir=dict(sizeLimit='30Gi'))])
        self.assertFalse(pod['spec']['automountServiceAccountToken'])
        for key in ['hostPID','hostIPC','hostNetwork']:
            self.assertFalse(pod['spec'].get(key,False))

    def test_every_catalog_entry_matches_actual_helm_pod(self):
        from runner_catalog import rendered_values, validate_rendered, validate_workflows
        values = rendered_values()
        validate_rendered(values)
        validate_workflows()
        rendered = {}
        for name, value in values.items():
            with TemporaryDirectory() as directory:
                path = Path(directory) / 'values.yaml'
                path.write_text(yaml.safe_dump(value))
                docs = self.render('live/kubernetes/homelab-management/.terraform/gha-runner-scale-set-0.14.2.tgz',
                                   name=name, namespace='arc-runners', values=path)
                rendered[name] = next(d for d in docs if d['kind'] == 'AutoscalingRunnerSet')['spec']
        validate_rendered(rendered)

    def test_workload_webhooks_are_filtered_and_stop_updates_bypass(self):
        raw = self.render('live/kubernetes/homelab-management/.terraform/kueue-0.19.4.tgz',name='kueue',
                          namespace='kueue-system',values='config/environments/kubernetes/homelab-ci/kueue-values.yaml')
        config = next(d for d in raw if d['kind']=='ConfigMap' and d['metadata']['name']=='kueue-manager-config')
        manager = yaml.safe_load(config['data']['controller_manager_config.yaml'])
        self.assertEqual(manager['integrations']['frameworks'],['pod','deployment'])
        self.assertFalse(manager['manageJobsWithoutQueueName'])
        self.assertEqual(manager['resources']['excludeResourcePrefixes'], [])
        render = module('postrender','scripts/kueue-postrender.py').render
        hooks = [h for d in render(raw) if d['kind'].endswith('WebhookConfiguration') for h in d['webhooks']]
        for name in ['mpod.kb.io','vpod.kb.io','mdeployment.kb.io','vdeployment.kb.io']:
            hook = next(h for h in hooks if h['name']==name)
            self.assertEqual(hook['failurePolicy'],'Fail')
            self.assertEqual(hook['objectSelector']['matchExpressions'][0]['operator'],'Exists')
            if 'deployment' in name:
                self.assertIn('object.spec.replicas != 0',hook['matchConditions'][-1]['expression'])
                self.assertIn('oldObject.spec.template',hook['matchConditions'][-1]['expression'])

    def test_only_execution_workflows_are_queued(self):
        docs = self.render('charts/homelab-jobs')
        for workflow in [d for d in docs if d['kind']=='WorkflowTemplate']:
            spec = workflow['spec']
            patch = json.loads(spec['podSpecPatch'])
            if workflow['metadata']['name'].startswith('ai-'):
                self.assertNotIn('kueue.x-k8s.io/queue-name',spec['podMetadata']['labels'])
                self.assertNotIn('schedulingGates',patch)
            else:
                self.assertEqual(spec['podMetadata']['labels']['kueue.x-k8s.io/queue-name'],'argo')
                self.assertNotIn('activeDeadlineSeconds',spec)
                self.assertIn('signal.alarm(300)',spec['templates'][0]['container']['args'][0])
                self.assertTrue(patch['schedulingGates'])
        cron = next(d for d in docs if d['kind']=='CronWorkflow')['spec']
        self.assertEqual((cron['timezone'],cron['concurrencyPolicy']),('UTC','Forbid'))

    def test_bootstrap_stays_hosted_and_routine_gates_allow_cancellation(self):
        for name in ['homelab-ci-admission','homelab-worker-maintenance','homelab-lifecycle-maintenance']:
            workflow=yaml.load((ROOT/'.github/workflows'/f'{name}.yml').read_text(),Loader=yaml.BaseLoader)
            for job in workflow['jobs'].values():
                if 'runs-on' in job: self.assertNotIn('CI_EXECUTOR',job['runs-on'])
        for name,key in [('tofu-plan','plan-gate'),('tofu-apply','apply-gate'),('sdk-publish-stable','publish-gate')]:
            workflow=yaml.load((ROOT/'.github/workflows'/f'{name}.yml').read_text(),Loader=yaml.BaseLoader)
            self.assertIn('!cancelled()' if name == 'sdk-publish-stable' else 'always()', workflow['jobs'][key]['if'])
        for p in (ROOT/'.github/workflows').glob('*.yml'):
            for job in yaml.load(p.read_text(),Loader=yaml.BaseLoader)['jobs'].values():
                if 'CI_EXECUTOR' in str(job.get('runs-on','')):
                    if p.stem in ('gitleaks', 'ubuntu-gpu-inference'):
                        self.assertIn("head.repo.full_name != github.repository && 'ubuntu-latest'", job['runs-on'])
                    else:
                        self.assertIn('head.repo.full_name == github.repository',job['if'])
                    self.assertIn('fromJSON',job['runs-on'])

    def test_deployment_locks_are_held_by_mutating_jobs_only(self):
        lock = {'group': 'tofu-apply', 'cancel-in-progress': 'false'}
        apply = yaml.load((ROOT/'.github/workflows/tofu-apply.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertNotIn('concurrency', apply)
        locked = {name for name, job in apply['jobs'].items() if 'concurrency' in job}
        self.assertEqual(locked, {'apply', 'worker-maintenance', 'acceptance', 'lifecycle-maintenance'})
        for name in locked:
            self.assertEqual(apply['jobs'][name]['concurrency'], lock, name)
        sdk = yaml.load((ROOT/'.github/workflows/sdk-publish-stable.yml').read_text(), Loader=yaml.BaseLoader)
        self.assertNotIn('concurrency', sdk)
        self.assertEqual(sdk['jobs']['publish-stable']['concurrency'],
                         {'group': 'sdk-publish-stable-${{ matrix.target }}', 'cancel-in-progress': 'false'})

    def test_status_needs_no_registry_or_helm_access(self):
        helper = module('homelab_ci_status', 'scripts/homelab-ci.py')
        with TemporaryDirectory() as directory:
            kubeconfig = Path(directory) / 'kubeconfig'
            kubeconfig.write_text('private test identity')
            kubeconfig.chmod(0o600)
            with patch.object(sys, 'argv', ['homelab-ci.py', 'status', '--private', directory]), \
                    patch.dict(os.environ, {}, clear=True), \
                    patch.object(helper, 'run', side_effect=[b'{"items":[]}', b'{"items":[]}', b'{"spec":{"queueingStrategy":"BestEffortFIFO","resourceGroups":[]}}']), \
                    patch.object(helper, 'artifacts') as fetch, redirect_stdout(io.StringIO()):
                helper.main()
            fetch.assert_not_called()

    def test_operator_status_resolves_exact_peer_without_token_in_arguments(self):
        helper = module('ai_control', 'scripts/ai-control.py')
        with TemporaryDirectory() as directory:
            credentials = Path(directory) / 'credentials.json'
            token = 'q' * 43
            credentials.write_text(json.dumps({'operator': token}))
            credentials.chmod(0o600)
            with patch.object(sys, 'argv', ['ai-control.py', 'status', '--credentials', str(credentials)]), \
                    patch.object(helper.apps, 'tailnet_https', return_value=b'{"observed":"Off"}') as request, \
                    redirect_stdout(io.StringIO()):
                helper.main()
            host, path, options, stdin = request.call_args.args
            self.assertEqual((host, path), ('ai-lifecycle.tail2f646b.ts.net', '/status'))
            self.assertNotIn(token, ' '.join(options))
            self.assertIn(token.encode(), stdin)

    def test_ci_plan_cannot_destroy_or_switch_namespaces(self):
        guard=module('homelab_ci','scripts/homelab-ci.py').guard
        plan={'resource_changes':[{'address':'helm_release.kueue','change':{'actions':['create'],
             'after':{'namespace':'kueue-system','version':'0.19.4'}}}]}
        self.assertEqual(guard(plan),['helm_release.kueue'])
        plan['resource_changes'][0]['change']['actions']=['delete']
        with self.assertRaises(ValueError):guard(plan)
        plan['resource_changes'][0]['change']['actions']=['create']
        plan['resource_changes'][0]['change']['after']['namespace']='kube-system'
        with self.assertRaises(ValueError):guard(plan)
