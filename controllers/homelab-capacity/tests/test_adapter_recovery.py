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

    from homelab_capacity.errors import RetryObservation
    from homelab_capacity.imm2 import IPMITransport, PowerError

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


@pytest.mark.parametrize(
    "diagnostic",
    [
        "Error from server (TooManyRequests): private-body",
        "Error from server (InternalError): private-body",
        "Error from server (ServiceUnavailable): private-body",
        "Error from server (ServerTimeout): private-body",
        "Error from server (Timeout): private-body",
        "Unable to connect to the server: EOF",
        "Unable to connect to the server: dial tcp: network is unreachable",
        "Unable to connect to the server: dial tcp: no route to host",
        "Unable to connect to the server: temporary failure in name resolution",
        "Unable to connect to the server: http2: client connection lost",
    ],
)
def test_transient_api_failures_reobserve(monkeypatch, diagnostic):
    from homelab_capacity.errors import RetryObservation

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr=diagnostic),
    )
    with pytest.raises(RetryObservation) as caught:
        Kube({"kubectl": "kubectl", "kubeconfig": "private"}).run("patch", "nodes")
    assert "private-body" not in str(caught.value)


@pytest.mark.parametrize(
    "fresh_uid,fresh_version,retry",
    [
        ("u", "2", True),
        ("u", "1", False),
        ("replacement", "2", False),
    ],
)
def test_generic_invalid_guarded_patch_checks_identity_and_version(
    monkeypatch, fresh_uid, fresh_version, retry
):
    import json

    from homelab_capacity.errors import RetryObservation

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if "get" in command:
            return SimpleNamespace(
                returncode=0,
                stderr="",
                stdout=json.dumps(
                    {"metadata": {"uid": fresh_uid, "resourceVersion": fresh_version}}
                ),
            )
        return SimpleNamespace(
            returncode=1,
            stdout="",
            stderr=(
                "The request is invalid: the server rejected our request due to an error in our request"
            ),
        )

    monkeypatch.setattr(subprocess, "run", run)
    kube = Kube({"kubectl": "kubectl", "kubeconfig": "private"})
    with pytest.raises(RuntimeError) as caught:
        kube.guarded(
            "cronjobs",
            {
                "metadata": {
                    "name": "cache-monitor",
                    "namespace": "homelab-cache",
                    "uid": "u",
                    "resourceVersion": "1",
                }
            },
            [{"op": "add", "path": "/spec/suspend", "value": True}],
        )
    assert isinstance(caught.value, RetryObservation) is retry
    assert len(calls) == 2
    assert "get" in calls[1] and "homelab-cache" in calls[1]
    if retry:
        state = State(phase="draining", pending="quiesce", deadline=500)
        complete(state, "quiesce", retry=str(caught.value))
        assert state.phase == "draining" and state.deadline == 500
        assert (
            decide(
                state, Observation(power="on", identity_ok=True), 500, mode="automatic"
            )
            is None
        )
        assert state.phase == "blocked"


@pytest.mark.parametrize(
    "diagnostic",
    [
        "Error from server (Forbidden): timeout policy denies access",
        "Error from server (Unauthorized): credentials expired",
        "Error from server (Invalid): spec.timeout invalid",
        "Error from server (NotFound): object not found",
        "Unable to connect to the server: x509: certificate has expired",
    ],
)
def test_permanent_api_failures_remain_blocking(monkeypatch, diagnostic):
    from homelab_capacity.errors import RetryObservation

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(returncode=1, stdout="", stderr=diagnostic),
    )
    with pytest.raises(RuntimeError) as caught:
        Kube({"kubectl": "kubectl", "kubeconfig": "private"}).run("patch", "nodes")
    assert not isinstance(caught.value, RetryObservation)


def test_readiness_client_timeout_reobserves(monkeypatch):
    from homelab_capacity.errors import RetryObservation

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("kubectl", 30)

    monkeypatch.setattr(subprocess, "run", timeout)
    with pytest.raises(RetryObservation):
        Kube({"kubectl": "kubectl", "kubeconfig": "private"}).wait(
            "rollout", "status", "deployment/example"
        )
