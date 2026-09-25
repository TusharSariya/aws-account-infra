"""Exercise ARM helper reuse without invoking Docker or AWS."""
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class OptimizationTests(unittest.TestCase):
    def test_arm_image_built_once_for_tests_and_packaging(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            docker = directory / 'docker'
            docker.write_text('''#!/bin/bash
set -eu
case "$1 $2" in
  "image inspect") test -e "$STUB_ROOT/image" ;;
  "buildx build") touch "$STUB_ROOT/image"; echo build >> "$STUB_ROOT/log" ;;
  run*) echo run >> "$STUB_ROOT/log" ;;
  *) exit 1 ;;
esac
''')
            docker.chmod(0o755)
            env={'PATH':temp+':'+os.environ['PATH'],'STUB_ROOT':temp}
            for operation in ['test','package']:
                subprocess.run(['bash',str(ROOT/'scripts/lambda-package-arm.sh'),operation,'fixture'],env=env,check=True)
            self.assertEqual((directory/'log').read_text().splitlines(), ['build','run','run'])

    def test_completed_run_metrics_preserve_unknown_wait_times(self):
        spec=importlib.util.spec_from_file_location('timings',ROOT/'scripts/ci-run-report.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        run={'id':1,'html_url':'https://example.invalid/run/1','head_sha':'a'*40,'conclusion':'success','status':'completed','created_at':'2026-09-24T00:00:00Z'}
        jobs=[{'name':'test','conclusion':'success','started_at':'2026-09-24T00:01:00Z','completed_at':'2026-09-24T00:02:00Z'}]
        result=module.report(run,jobs,'cold',{})
        self.assertEqual(result['runner_seconds'],60)
        self.assertEqual(result['elapsed_seconds'],120)
        self.assertIsNone(result['jobs'][0]['queue_seconds'])
        self.assertEqual(result['cache_state'],'cold')
