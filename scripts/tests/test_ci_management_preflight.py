"""Planning is read-only; deployment must wait for assigned or gated runners."""
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

import pytest

spec = importlib.util.spec_from_file_location('ci_management', Path(__file__).parents[1] / 'homelab-ci.py')
ci = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci)


def pod(owner, phase='Running'):
    return {'metadata': {'namespace': 'arc-runners', 'ownerReferences': [{'kind': owner}]},
            'status': {'phase': phase}}


def test_management_plan_accepts_running_jobs_and_listeners():
    nodes = [{'metadata': {'name': name}, 'status': {
        'allocatable': {'cpu': '64', 'memory': '256Gi'},
        'conditions': [{'type': 'Ready', 'status': 'True'}]}}
        for name in ('talos-cp-01', 'talos-worker-01', 'talos-worker-02')]
    def run(command, *args):
        if 'nodes' in command:
            return json.dumps({'items': nodes})
        if 'pods' in command:
            return json.dumps({'items': [pod('AutoscalingListener'), pod('EphemeralRunner')]})
        return b''
    with patch.object(ci, 'run', side_effect=run):
        assert ci.management_preflight(['kubectl'])['talos-worker-01']['ready']


def test_apply_idle_guard_ignores_listeners_but_rejects_running_and_gated_jobs():
    ci.require_idle_runners([pod('AutoscalingListener'), pod('EphemeralRunner', 'Succeeded')])
    for phase in ('Running', 'Pending'):
        with pytest.raises(ValueError, match='runners'):
            ci.require_idle_runners([pod('EphemeralRunner', phase)])
    with pytest.raises(ValueError, match='runners'):
        ci.require_idle_runners([pod('UnknownOwner')])


def test_existing_arc_identity_is_verified_without_mutation():
    import base64
    data = {key: base64.b64encode(value.encode()).decode() for key, value in {
        'github_app_id': '123', 'github_app_installation_id': '456',
        'github_app_private_key': 'test-only-private-key',
    }.items()}
    secret = {'type': 'Opaque', 'data': data}
    with patch.object(ci, 'run', return_value=json.dumps(secret).encode()) as command:
        ci.enroll(['kubectl'], None)
    command.assert_called_once_with(['kubectl', 'get', 'secret', 'github-app', '-n', 'arc-runners', '-o', 'json'])
    for invalid in [None, {}, {'type': 'Opaque', 'data': {}},
                    {'type': 'Opaque', 'data': dict(data, github_app_private_key='@@@')},
                    {'type': 'Opaque', 'data': dict(data, github_app_private_key='')},
                    {'type': 'Opaque', 'data': dict(data, unexpected='eA==')}]:
        with patch.object(ci, 'run', return_value=json.dumps(invalid).encode()), pytest.raises(ValueError, match='bootstrap'):
            ci.enroll(['kubectl'], None)
