"""Exercise ARM helper reuse without invoking Docker or AWS."""
import collections
import importlib.util
import os
from pathlib import Path
import re
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
PINS = ROOT / 'config/ci-python-pins.txt'
WITH_PIN = re.compile(
    r"""--with[ =](['"]?)([A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[A-Za-z0-9_.+!-]+)\1""")
CACHE_ACTION = re.compile(r'uses: \./\.github/actions/(nexus-dependency-cache|talos-build-cache)\s*$')


def ci_files():
    return sorted((ROOT / '.github/workflows').glob('*.yml')) + sorted((ROOT / '.github/actions').rglob('*.yml'))


def cache_calls(path):
    """Return action/job/kind/scope per cache step; plain text so no PyYAML is needed."""
    calls, job, current, in_jobs = [], None, None, False
    for line in path.read_text().splitlines():
        if line and not line[0].isspace():
            in_jobs, current = line.rstrip() == 'jobs:', None
            continue
        match = re.fullmatch(r'  ([A-Za-z0-9_-]+):\s*', line)
        if in_jobs and match:
            job, current = match.group(1), None
            continue
        match = CACHE_ACTION.search(line)
        if match:
            current = {'action': match.group(1), 'job': job, 'kind': '', 'scope': ''}
            calls.append(current)
            continue
        if current is not None:
            if re.match(r'\s+- ', line):
                current = None
            elif match := re.fullmatch(r'\s+(kind|scope):\s*(.*?)\s*', line):
                current[match.group(1)] = match.group(2)
    return calls


class CacheKeyTests(unittest.TestCase):
    def test_python_cache_key_tracks_pins_not_workflow_text(self):
        pins = set(PINS.read_text().split())
        used = {m.group(2) for path in ci_files() for m in WITH_PIN.finditer(path.read_text())}
        self.assertTrue(used)
        self.assertEqual(sorted(used - pins), [], 'add these --with pins to config/ci-python-pins.txt')
        self.assertEqual(sorted(pins - used), [], 'remove stale pins from config/ci-python-pins.txt')
        hashes = 0
        for path in ci_files():
            for line in path.read_text().splitlines():
                if 'hashFiles(' in line and 'uv.lock' in line:
                    hashes += 1
                    self.assertNotIn('.github/workflows/*.yml', line, path.name)
                    self.assertIn("'config/ci-python-pins.txt'", line, path.name)
        self.assertGreater(hashes, 0)

    def test_cache_scopes_are_unique_across_workflow_files(self):
        # Cache actions scope by job id (not caller workflow name) so PR and main
        # callers of one reusable workflow share main's read-only fallback. A job
        # id reused in another workflow file must pass a distinguishing scope.
        owners = collections.defaultdict(set)
        for path in sorted((ROOT / '.github/workflows').glob('*.yml')):
            for call in cache_calls(path):
                owners[(call['action'], call['job'], call['kind'], call['scope'])].add(path.name)
        self.assertTrue(owners)
        collisions = {k: sorted(v) for k, v in owners.items() if len(v) > 1}
        self.assertEqual(collisions, {})
        for action in ('nexus-dependency-cache', 'talos-build-cache'):
            text = (ROOT / '.github/actions' / action / 'action.yml').read_text()
            self.assertNotIn('github.workflow }}', text)


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
        jobs=[{'name':'test','runner_name':'fixture-runner','conclusion':'success','started_at':'2026-09-24T00:01:00Z','completed_at':'2026-09-24T00:02:00Z'}]
        result=module.report(run,jobs,'cold',{})
        self.assertEqual(result['runner_seconds'],60)
        self.assertEqual(result['elapsed_seconds'],120)
        self.assertIsNone(result['jobs'][0]['queue_seconds'])
        self.assertEqual(result['cache_state'],'cold')
        self.assertIsNone(module.elapsed('2026-09-24T00:02:00Z', '2026-09-24T00:01:00Z'))
        jobs[0].pop('runner_name')
        self.assertEqual(module.report(run,jobs,'cold',{})['runner_seconds'], 0)

    def test_rerun_metrics_exclude_previous_attempt_wait_and_reused_jobs(self):
        spec=importlib.util.spec_from_file_location('timings',ROOT/'scripts/ci-run-report.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        run={'id':1,'html_url':'https://example.invalid/run/1','head_sha':'a'*40,'conclusion':'success','status':'completed','created_at':'2026-09-24T00:00:00Z','run_attempt':2,'run_started_at':'2026-09-24T01:00:00Z'}
        jobs=[{'name':'reused','runner_name':'old-runner','conclusion':'success','started_at':'2026-09-24T00:01:00Z','completed_at':'2026-09-24T00:02:00Z'},
              {'name':'retried','runner_name':'new-runner','conclusion':'success','created_at':'2026-09-24T01:00:00Z','started_at':'2026-09-24T01:01:00Z','completed_at':'2026-09-24T01:02:00Z'}]
        result=module.report(run,jobs,'warm',{})
        self.assertEqual(result['elapsed_seconds'],120)
        self.assertEqual(result['runner_seconds'],60)
        self.assertEqual(result['run_attempt'],2)
        self.assertTrue(result['jobs'][0]['reused_from_previous_attempt'])
        self.assertEqual(result['jobs'][1]['queue_seconds'],60)
