"""Adapter failures expose bounded recovery categories without raw private output."""

import subprocess
from types import SimpleNamespace

import pytest

from homelab_capacity.kube import Kube
from homelab_capacity.lifecycle import Observation, State, complete, decide


def test_conflicting_patch_reobserves_without_clearing_deadline(monkeypatch):
    from homelab_capacity.errors import RetryObservation

    kube = Kube({"kubectl": "kubectl", "kubeconfig": "private"})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="testing value /metadata/resourceVersion failed: test failed; private-body",
        ),
    )
    state = State(phase="restoring", pending="restore", deadline=500)
    with pytest.raises(RetryObservation) as caught:
        kube.guarded(
            "nodes",
            {"metadata": {"name": "worker", "uid": "u", "resourceVersion": "1"}},
            [],
        )
    assert "private-body" not in str(caught.value)
    complete(state, "restore", retry=str(caught.value))
    assert state.deadline == 500
    assert (
        decide(
            state,
            Observation(power="on", identity_ok=True, ready=False, complete=True),
            10,
            mode="automatic",
        )
        == "restore"
    )
    complete(state, "restore", retry="conflict")
    assert (
        decide(state, Observation(power="on", identity_ok=True), 500, mode="automatic")
        is None
    )
    assert state.phase == "blocked"


def test_forbidden_patch_is_not_retried(monkeypatch):
    from homelab_capacity.errors import RetryObservation

    kube = Kube({"kubectl": "kubectl", "kubeconfig": "private"})
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="Error from server (Forbidden): private-body",
        ),
    )
    with pytest.raises(RuntimeError) as caught:
        kube.run("patch", "nodes")
    assert not isinstance(caught.value, RetryObservation)
    assert "private-body" not in str(caught.value)


@pytest.mark.parametrize("action", ["status", "start-worker"])
def test_pve_transport_failure_reobserves_safe_operations(monkeypatch, action):
    from homelab_capacity.errors import RetryObservation
    from homelab_capacity.management import Management

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=255, stdout="", stderr="private diagnostic"
        ),
    )
    with pytest.raises(RetryObservation, match=action):
        Management({"known_hosts": "known", "pve_key": "key"}).pve("primary", action)


def test_lost_poweroff_acknowledgement_is_never_a_blind_retry(monkeypatch):
    from homelab_capacity.errors import UncertainShutdown
    from homelab_capacity.management import Management

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=255, stdout="", stderr="private diagnostic"
        ),
    )
    with pytest.raises(UncertainShutdown):
        Management({"known_hosts": "known", "pve_key": "key"}).pve(
            "primary", "poweroff"
        )


def test_lost_talos_shutdown_acknowledgement_observes_completion(monkeypatch):
    from homelab_capacity.errors import UncertainShutdown
    from homelab_capacity.management import Management

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout="", stderr="private diagnostic"
        ),
    )
    with pytest.raises(UncertainShutdown):
        Management({"talosctl": "talosctl", "talosconfig": "private"}).talos(
            "primary", "shutdown", "--wait=false"
        )


def test_truncated_poweroff_response_is_uncertain_not_permanent_failure(monkeypatch):
    from homelab_capacity.errors import UncertainShutdown
    from homelab_capacity.management import Management

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout="{", stderr=""),
    )
    with pytest.raises(UncertainShutdown):
        Management({"known_hosts": "known", "pve_key": "key"}).pve(
            "primary", "poweroff"
        )


def test_ipmi_timeout_is_retryable_but_invalid_credential_is_not(monkeypatch):
    from pathlib import Path
    from homelab_capacity.imm2 import IPMITransport, PowerError
    from homelab_capacity.errors import RetryObservation

    transport = IPMITransport(Path("/private"), "primary")

    def timeout(*a, **kw):
        raise subprocess.TimeoutExpired("ipmi", 25)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RetryObservation):
        transport.request_on()
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(
            returncode=1, stdout='{"error":"PermissionError"}'
        ),
    )
    with pytest.raises(PowerError) as caught:
        transport.request_on()
    assert not isinstance(caught.value, RetryObservation)
