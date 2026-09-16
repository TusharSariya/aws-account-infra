"""Keep Workflow acceptance independent of kubectl's discovery cache."""
import importlib.util
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('lifecycle_acceptance', Path(__file__).resolve().parents[1] / 'homelab-lifecycle-validate.py')
validate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validate)


class WorkflowDryRunTests(unittest.TestCase):
    def test_fixed_endpoint_preserves_impersonation_strict_validation_and_dry_run(self):
        value = {'apiVersion': 'argoproj.io/v1alpha1', 'kind': 'Workflow',
                 'metadata': {'generateName': 'admission-proof-', 'namespace': 'homelab-jobs'},
                 'spec': {'workflowTemplateRef': {'name': 'smoke'}}}
        with patch.object(validate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, b'', b'')) as run:
            validate.dry_run(value, True)
        command = list(map(str, run.call_args.args[0]))
        self.assertIn('--as=' + validate.CLIENT, command)
        self.assertIn('--raw=/apis/argoproj.io/v1alpha1/namespaces/homelab-jobs/workflows?fieldValidation=Strict&dryRun=All', command)
        self.assertNotIn('--validate=false', command)

    def test_unrelated_rejection_cannot_pass_negative_acceptance(self):
        with patch.object(validate.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1, b'', b'connection refused')):
            with self.assertRaisesRegex(validate.apps.AppError, 'not enforced'):
                validate.dry_run({}, False)
