#!/usr/bin/env python3
"""Start or monitor the isolated 24-hour GitHub queue expiry proof from the Mac."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

REPO = 'TusharSariyaOrg/aws-account-infra'
IMAGE = 'python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6'


def command(args, value=None):
    result = subprocess.run(args, input=None if value is None else json.dumps(value), text=True,
                            capture_output=True, timeout=120)
    if result.returncode:
        raise ValueError('Command failed: ' + args[0] + '; private output suppressed')
    return result.stdout


def now():
    return datetime.now(timezone.utc).isoformat()


def api(path):
    for attempt in range(3):
        try:
            return json.loads(command(['gh', 'api', 'repos/' + REPO + '/' + path]))
        except (ValueError, subprocess.TimeoutExpired):
            if attempt == 2:
                raise
            time.sleep(5 * (attempt + 1))


def kubectl(private, *args, value=None):
    return command(['kubectl', '--kubeconfig', str(private / 'kubeconfig'), '--request-timeout=30s',
                    *args], value)


def objects(private, kind):
    return json.loads(kubectl(private, 'get', kind, '-A', '-o', 'json'))['items']


def finished(workload):
    return any(c['type'] == 'Finished' and c['status'] == 'True'
               for c in workload.get('status', {}).get('conditions', []))


def save(private, record):
    (private / 'expiry-record.json').write_text(json.dumps(record, indent=2) + '\n')


def remove_blocker(private, record):
    # UID precondition prevents touching a replacement object, even after a crash.
    matches = [p for p in objects(private, 'pods') if p['metadata']['uid'] == record['blocker_uid']]
    if matches:
        kubectl(private, 'delete', '--raw=/api/v1/namespaces/homelab-jobs/pods/' + record['blocker'],
                '-f', '-', value={'apiVersion': 'v1', 'kind': 'DeleteOptions',
                                 'preconditions': {'uid': record['blocker_uid']}})


def start(private, ref):
    if (private / 'expiry-record.json').exists():
        raise ValueError('Use a new private directory; preserve earlier attempts')
    if any(not finished(w) for w in objects(private, 'workloads')):
        raise ValueError('Quiesce all AI, CI and Argo work before starting expiry observation')
    deployment = json.loads(kubectl(private, 'get', 'deployment', 'ai-runtime', '-n', 'homelab-models', '-o', 'json'))
    if deployment['spec']['replicas'] != 0:
        raise ValueError('AI must remain Off')
    fixture = uuid.uuid4().hex
    record = dict(fixture_id=fixture, blocker='arc-expiry-' + fixture[:12], started_at=now(),
                  state='starting', ref=ref, github_run=None, candidates=[])
    resources = {'cpu': '36', 'memory': '64Mi', 'ephemeral-storage': '16Mi'}
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': record['blocker'], 'namespace': 'homelab-jobs',
           'labels': {'homelab/acceptance-run': fixture, 'kueue.x-k8s.io/queue-name': 'argo',
                      'kueue.x-k8s.io/workload-priority-class': 'homelab-compute'}},
           'spec': {'serviceAccountName': 'homelab-job', 'automountServiceAccountToken': False,
                    'restartPolicy': 'Never', 'terminationGracePeriodSeconds': 1, 'activeDeadlineSeconds': 26*3600,
                    'schedulingGates': [{'name': 'kueue.x-k8s.io/admission'}],
                    'securityContext': {'runAsNonRoot': True, 'runAsUser': 8737, 'seccompProfile': {'type': 'RuntimeDefault'}},
                    'containers': [{'name': 'hold', 'image': IMAGE, 'command': ['python', '-B', '-c', 'import time; time.sleep(93600)'],
                                    'securityContext': {'readOnlyRootFilesystem': True, 'allowPrivilegeEscalation': False,
                                                        'capabilities': {'drop': ['ALL']}},
                                    'resources': {'requests': resources, 'limits': resources}}]}}
    created = json.loads(kubectl(private, 'create', '-f', '-', '-o', 'json', value=pod))
    record['blocker_uid'] = created['metadata']['uid']
    save(private, record)
    try:
        kubectl(private, 'wait', '--for=condition=Ready', 'pod/' + record['blocker'], '-n', 'homelab-jobs', '--timeout=90s')
        command(['gh', 'workflow', 'run', 'homelab-arc-acceptance.yml', '--repo', REPO, '--ref', ref,
                 '-f', 'scenario=expiry', '-f', 'fixture_id=' + fixture, '-f', 'confirm=observe-24h-expiry'])
        for _ in range(30):
            runs = api('actions/workflows/homelab-arc-acceptance.yml/runs?event=workflow_dispatch&per_page=30')['workflow_runs']
            matches = [r for r in runs if r['display_title'] == 'ARC expiry ' + fixture]
            if len(matches) == 1:
                record['github_run'] = matches[0]['id']
                record['github_created_at'] = matches[0]['created_at']
                record['source_sha'] = matches[0]['head_sha']
                break
            time.sleep(2)
        if record['github_run'] is None:
            raise ValueError('Dispatched run could not be identified; inspect the unique fixture title')
        record['state'] = 'watching'
        save(private, record)
        # Freeze the observer source independently of worktree edits or removal.
        script = private / 'expiry-monitor.py'
        shutil.copyfile(__file__, script)
        with (private / 'expiry-monitor.log').open('a') as log:
            process = subprocess.Popen([sys.executable, str(script), 'watch', '--private', str(private)],
                                       cwd=private, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                       start_new_session=True)
        record['monitor_pid'] = process.pid
        if sys.platform == 'darwin':
            # Keep the independent Mac observer awake only for its own lifetime.
            subprocess.Popen(['/usr/bin/caffeinate', '-i', '-w', str(process.pid)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        save(private, record)
        print(json.dumps(record, indent=2))
    except Exception:
        remove_blocker(private, record)
        record['state'] = 'start-failed'; save(private, record)
        raise


def observe_runner_ownership(record, pods):
    # Isolated initial quiescence identifies the fixture's scale set. Retain
    # replacement UIDs too so a recreated runner cannot escape cleanup checks.
    candidates = [p for p in pods if p['metadata']['namespace'] == 'arc-runners'
                  and p['metadata']['name'].startswith('homelab-talos-light-')]
    if len(candidates) > 1:
        raise ValueError('Ambiguous expiry runner ownership; preserve evidence and retry in isolation')
    if candidates and candidates[0]['metadata']['uid'] not in record['candidates']:
        record['candidates'].append(candidates[0]['metadata']['uid'])


def watch(private):
    record = json.loads((private / 'expiry-record.json').read_text())
    started = datetime.fromisoformat(record['github_created_at'].replace('Z', '+00:00')).timestamp()
    record['monitor_pid'] = os.getpid()
    record['monitor_started_at'] = now()
    previous = time.time()
    record['observation_gap'] = False
    try:
        while time.time() - started < 26*3600:
            sampled = time.time()
            record['observation_gap'] |= sampled - previous > 600
            previous = sampled
            jobs = api(f"actions/runs/{record['github_run']}/jobs?per_page=100")['jobs']
            job = next((j for j in jobs if j['name'] == 'expiry'), None)
            record['job_status'] = job['status'] if job else 'unknown'
            sample = dict(observed_at=now(), job=job)
            with (private / 'expiry-observations.jsonl').open('a') as output:
                output.write(json.dumps(sample) + '\n')
            observe_runner_ownership(record, objects(private, 'pods'))
            record['last_observed_at'] = now()
            save(private, record)
            if job and (job.get('runner_id') or job.get('steps')):
                raise ValueError('Expiry fixture acquired a runner; queue-timeout proof failed')
            if job and job['status'] == 'completed':
                elapsed = sampled - started
                record['elapsed_seconds'] = elapsed
                record['conclusion'] = job['conclusion']
                if elapsed < 24*3600 or record['observation_gap']:
                    raise ValueError('Premature completion or observation gap; not a verified 24-hour expiry')
                check_id = job['check_run_url'].rsplit('/', 1)[-1]
                record['annotations'] = api('check-runs/' + check_id + '/annotations')
                # Preserve the reason for review; cancellation alone is not proof.
                record['state'] = 'completed-awaiting-expiry-reason-review'
                break
            time.sleep(60)
        else:
            raise ValueError('26-hour observer deadline exceeded')
    except Exception as error:
        record['state'] = 'failed-or-interrupted'
        record['error'] = str(error)
    finally:
        # Stop only this dispatched fixture before releasing capacity on an
        # interrupted observation. Cancellation is never recorded as expiry.
        if record.get('job_status') != 'completed':
            try:
                command(['gh', 'run', 'cancel', str(record['github_run']), '--repo', REPO])
                record['fixture_cancel_requested'] = True
            except (ValueError, subprocess.TimeoutExpired):
                record['fixture_cancel_requested'] = False
        remove_blocker(private, record)
        owned = {record['blocker_uid'], *record['candidates']}
        for _ in range(60):
            pods = [p for p in objects(private, 'pods') if p['metadata']['uid'] in owned]
            workloads = [w for w in objects(private, 'workloads') if any(
                o['uid'] in owned for o in w['metadata'].get('ownerReferences', []))]
            if not pods and not workloads:
                record['cleanup_observed'] = True
                break
            time.sleep(5)
        else:
            record['cleanup_observed'] = False
        record['finished_at'] = now()
        save(private, record)
        print(json.dumps(record, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['start', 'watch'])
    parser.add_argument('--private', required=True, type=Path)
    parser.add_argument('--ref', default='feat/job-sized-kueue-runners')
    args = parser.parse_args()
    os.umask(0o077)
    private = args.private.resolve()
    for path in [private, private / 'kubeconfig']:
        if path.is_symlink() or path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
            raise ValueError('Use an owned private directory and kubeconfig')
    if args.operation == 'start':
        start(private, args.ref)
    else:
        watch(private)


if __name__ == '__main__':
    main()
