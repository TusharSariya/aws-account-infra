from copy import deepcopy
import pytest
from homelab_node_readiness import verify


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
