from copy import deepcopy

import pytest
import re
from pathlib import Path

from homelab_node_readiness import NotReady, diagnostic, verify


def fixtures():
    nodes = [
        {
            "metadata": {"name": n},
            "spec": {},
            "status": {"conditions": [{"type": "Ready", "status": "True"}]},
        }
        for n in ["talos-cp-01", "talos-worker-01", "talos-worker-02"]
    ]
    pods = [
        {
            "metadata": {"ownerReferences": [{"kind": "DaemonSet", "name": d}]},
            "spec": {"nodeName": n["metadata"]["name"]},
            "status": deepcopy(n["status"]),
        }
        for n in nodes
        for d in ["cilium", "cilium-envoy", "kube-proxy"]
    ]
    return nodes, pods


def test_sleeping_secondary_does_not_block_network_acceptance():
    nodes, pods = fixtures()
    nodes[2]["status"]["conditions"][0]["status"] = "Unknown"
    nodes[2]["spec"]["unschedulable"] = True
    nodes[2]["metadata"]["annotations"] = {"homelab.tfdraw.dev/power-intent": "sleep"}
    verify(nodes, pods[:6])
    nodes[2]["metadata"]["annotations"] = {}
    with pytest.raises(ValueError, match="Unexpected unavailable"):
        verify(nodes, pods[:6])


def test_awake_node_requires_all_network_agents():
    nodes, pods = fixtures()
    verify(nodes, pods)
    with pytest.raises(ValueError, match="Networking is not ready"):
        verify(nodes, pods[:-1])
    nodes[1]["status"]["conditions"][0]["status"] = "False"
    nodes[1]["metadata"]["annotations"] = {"homelab.tfdraw.dev/power-intent": "sleep"}
    nodes[1]["spec"]["unschedulable"] = True
    with pytest.raises(ValueError, match="Unexpected unavailable"):
        verify(nodes, pods)


def test_quarantined_offline_desktop_does_not_gate_retained_servers():
    nodes, pods = fixtures()
    desktop = deepcopy(nodes[0])
    desktop['metadata']['name'] = 'ubuntu-gpu-01'
    desktop['status']['conditions'][0]['status'] = 'Unknown'
    desktop['spec']['taints'] = [
        {'key': 'homelab.tfdraw.dev/quarantine', 'value': 'true', 'effect': 'NoSchedule'},
        {'key': 'homelab.tfdraw.dev/compute', 'value': 'true', 'effect': 'NoSchedule'},
    ]
    verify(nodes + [desktop], pods)
    # Admission-enabled, unknown, and retained nodes never inherit this exception.
    for name in ['ubuntu-gpu-02', 'talos-worker-01', 'talos-cp-01']:
        other = deepcopy(desktop)
        other['metadata']['name'] = name
        with pytest.raises(ValueError, match='Unexpected unavailable'):
            verify([other], [])
    for missing in range(2):
        other = deepcopy(desktop)
        other['spec']['taints'].pop(missing)
        with pytest.raises(ValueError, match='Unexpected unavailable'):
            verify(nodes + [other], pods)
    desktop['status']['conditions'][0]['status'] = 'True'
    with pytest.raises(ValueError, match='Networking is not ready'):
        verify(nodes + [desktop], pods)


def test_timeout_diagnostic_names_only_the_unready_subject():
    nodes, pods = fixtures()
    source = (Path(__file__).resolve().parents[1] / "talos-ci.py").read_text()
    allow = re.search(r"re\.fullmatch\(r'(ACCEPTANCE_DIAGNOSTIC: [^']+)'", source).group(1)
    for broken, expected in [(pods[:-1], "talos-worker-02/kube-proxy"), (pods, None)]:
        if expected is None:
            nodes[1]["status"]["conditions"][0]["status"] = "False"
            expected = "talos-worker-01"
        with pytest.raises(NotReady) as raised:
            verify(nodes, broken)
        line = diagnostic(raised.value)
        assert line == "ACCEPTANCE_DIAGNOSTIC: readiness node " + expected
        assert re.fullmatch(allow, line)
    assert diagnostic(ValueError("other")) is None
    assert diagnostic(NotReady("x: ", "Bad Name; secret")) is None
