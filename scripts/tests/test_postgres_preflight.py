import json
import os
from pathlib import Path
import sys
import unittest
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

    def run_preflight(self, pods, strategy='BestEffortFIFO'):
        def run(command):
            if 'pods' in command: value = {'items': pods}
            elif 'deployment' in command: value = {'spec': {'replicas': 0}}
            elif 'clusterqueue' in command:
                value = {'spec': {'queueingStrategy': strategy, 'resourceGroups': [{'flavors': [{'resources': [
                    {'name': 'cpu', 'nominalQuota': '31.25'}, {'name': 'memory', 'nominalQuota': '90Gi'}, {'name':'ephemeral-storage','nominalQuota':'260Gi'}, {'name':'pods','nominalQuota':'90'}]}]}]}}
            elif 'storageclass' in command: value = {'reclaimPolicy': 'Retain', 'allowVolumeExpansion': False}
            else: value = {'mounted': True, 'free': 200 * 1024**3}
            return json.dumps(value).encode()
        return postgres_preflight.verify('kubectl', run)

    def test_dynamic_queue_policy_required_before_deployment(self):
        self.run_preflight([])
        with self.assertRaisesRegex(ValueError, 'dynamic capacity'):
            self.run_preflight([], strategy='StrictFIFO')

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
            with patch.dict(os.environ, environment, clear=True), patch('socket.gethostname', return_value='deploy-runner'):
                with self.assertRaisesRegex(ValueError, 'Wait for active'):
                    self.run_preflight([self.pod('deploy-runner')])

    def test_ai_is_never_exempt(self):
        pod = self.pod('deploy-runner')
        pod['metadata']['labels']['app'] = 'ai-runtime'
        with patch.dict(os.environ, {'GITHUB_ACTIONS': 'true', 'GITHUB_REPOSITORY': 'TusharSariyaOrg/aws-account-infra', 'RUNNER_NAME': 'deploy-runner'}, clear=True), patch('socket.gethostname', return_value='deploy-runner'):
            with self.assertRaisesRegex(ValueError, 'Wait for active'):
                self.run_preflight([pod])
