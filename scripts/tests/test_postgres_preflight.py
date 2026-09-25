import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import postgres_preflight


class DeploymentPreflightTests(unittest.TestCase):
    def pod(self, name):
        return {'metadata': {'name': name, 'namespace': 'arc-runners', 'labels': {
            'kueue.x-k8s.io/queue-name': 'ci',
            'app.kubernetes.io/component': 'runner',
            'actions.github.com/organization': 'TusharSariyaOrg',
            'actions.github.com/repository': 'aws-account-infra'}}, 'status': {'phase': 'Running'}}

    def run_preflight(self, pods, strategy='BestEffortFIFO', quotas=None, extra_quotas=None):
        def run(command):
            if 'pods' in command: value = {'items': pods}
            elif 'deployment' in command: value = {'spec': {'replicas': 0}}
            elif 'clusterqueue' in command:
                values = quotas or {'cpu': '31.25', 'memory': '90Gi', 'ephemeral-storage': '260Gi', 'pods': '90'}
                value = {'spec': {'queueingStrategy': strategy, 'resourceGroups': [{'flavors': [{'resources': [
                    {'name': name, 'nominalQuota': amount} for name, amount in values.items()]}]}]}}
                if extra_quotas is not None:
                    value['spec']['resourceGroups'][0]['flavors'].append({'resources': [
                        {'name': name, 'nominalQuota': amount} for name, amount in extra_quotas.items()]})
            elif 'storageclass' in command: value = {'reclaimPolicy': 'Retain', 'allowVolumeExpansion': False}
            else: value = {'mounted': True, 'free': 200 * 1024**3}
            return json.dumps(value).encode()
        return postgres_preflight.verify('kubectl', run)

    def test_dynamic_queue_policy_required_before_deployment(self):
        self.run_preflight([])
        self.run_preflight([], quotas={'cpu': '38', 'memory': '109Gi', 'ephemeral-storage': '280Gi', 'pods': '105'})
        with self.assertRaisesRegex(ValueError, 'dynamic capacity'):
            self.run_preflight([], strategy='StrictFIFO')

    def test_reviewed_rollback_queue_supports_transition_without_raising_limits(self):
        quotas = {'cpu': '31250m', 'memory': '84Gi', 'ephemeral-storage': '240Gi'}
        self.run_preflight([], strategy='StrictFIFO', quotas=quotas, extra_quotas=quotas)
        with self.assertRaises(ValueError):
            self.run_preflight([], strategy='StrictFIFO', quotas=quotas, extra_quotas={**quotas, 'memory': '90Gi'})
        for resource, value in [('cpu', '32'), ('memory', '90Gi'), ('ephemeral-storage', '250Gi')]:
            with self.subTest(resource=resource), self.assertRaises(ValueError):
                self.run_preflight([], strategy='StrictFIFO', quotas={**quotas, resource: value})
        with self.assertRaisesRegex(ValueError, 'Wait for active'):
            self.run_preflight([self.pod('other-runner')], strategy='StrictFIFO', quotas=quotas)

    def test_only_this_repositorys_own_runner_is_exempt(self):
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'TusharSariyaOrg/aws-account-infra', 'RUNNER_NAME': 'deploy-runner'}, clear=True), patch('socket.gethostname', return_value='deploy-runner'):
            self.run_preflight([self.pod('deploy-runner')])
            with self.assertRaisesRegex(ValueError, 'Wait for active'):
                self.run_preflight([self.pod('deploy-runner'), self.pod('other-runner')])
            spoofed = self.pod('deploy-runner')
            spoofed['metadata']['labels']['actions.github.com/repository'] = 'different-repository'
            with self.assertRaisesRegex(ValueError, 'Wait for active'):
                self.run_preflight([spoofed])

    def test_local_and_mismatched_runner_identity_cannot_exempt_work(self):
        for environment in ({}, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'TusharSariyaOrg/aws-account-infra', 'RUNNER_NAME': 'different-runner'}):
            with patch.dict(os.environ, environment, clear=True), patch('socket.gethostname', return_value='deploy-runner'), self.assertRaisesRegex(ValueError, 'Wait for active'):
                self.run_preflight([self.pod('deploy-runner')])

    def test_ai_is_never_exempt(self):
        pod = self.pod('deploy-runner')
        pod['metadata']['labels']['app'] = 'ai-runtime'
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'TusharSariyaOrg/aws-account-infra', 'RUNNER_NAME': 'deploy-runner'}, clear=True), patch('socket.gethostname', return_value='deploy-runner'), self.assertRaisesRegex(ValueError, 'Wait for active'):
            self.run_preflight([pod])
