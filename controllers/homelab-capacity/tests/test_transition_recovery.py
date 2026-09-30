"""Faults at real transition boundaries must converge without losing safety gates."""

from types import SimpleNamespace

from homelab_capacity.coordinator import Coordinator
from homelab_capacity.lifecycle import Observation, State, complete, decide, observe_off


def observation(**changes):
    return Observation(
        **(
            dict(power="on", identity_ok=True, ready=True, complete=True, quiesced=True)
            | changes
        )
    )


def test_final_demand_check_cancels_and_restores_instead_of_blocking():
    state = State(phase="draining")
    controller = object.__new__(Coordinator)
    controller.require_acceptance = lambda host: None
    controller.kube = SimpleNamespace(inventory=lambda: {})
    controller.observation = lambda host, objects: observation(demand=True)
    calls = []
    controller.management = SimpleNamespace(talos=lambda *args: calls.append(args))
    action = decide(state, observation(), 0, mode="automatic")
    outcome = controller.effect("primary", action, {})
    complete(state, action, outcome=outcome)
    assert not calls
    assert state.phase == "restoring"
    assert (
        decide(state, observation(ready=False, demand=True), 15, mode="automatic")
        == "restore"
    )


def test_restart_after_acknowledged_shutdown_observes_off_without_resending():
    state = State(phase="stopping", pending="await-off", deadline=30)
    state.restart()
    assert (
        decide(
            state, observation(vm_stopped=True, host_empty=True), 100, mode="automatic"
        )
        is None
    )
    off = observation(power="off", ready=False)
    observe_off(state, off)
    assert decide(state, off, 115, mode="automatic") is None
    assert state.phase == "off"


def test_restart_restores_partial_platform_operation_with_fresh_deadline():
    state = State(phase="restoring", pending="restore", deadline=99999)
    state.restart()
    assert decide(state, observation(ready=False), 0, mode="automatic") == "restore"
    assert state.deadline == 1200


def test_uncertain_stop_worker_waits_for_observed_vm_stop_not_duplicate_shutdown():
    state = State(phase="stopping", pending="stop-worker")
    state.restart()
    assert decide(state, observation(), 0, mode="automatic") is None
    assert (
        decide(
            state, observation(vm_stopped=True, host_empty=True), 15, mode="automatic"
        )
        == "stop-host"
    )


def test_restart_does_not_clear_identity_or_storage_block():
    state = State(phase="blocked", reason="Protected storage identity or mount changed")
    state.restart()
    assert decide(state, observation(demand=True), 0, mode="automatic") is None
    assert state.phase == "blocked"


def test_cancel_intent_survives_conflict_and_restart_without_immediate_shutdown():
    state = State(phase="draining", shutdown_requested=True)
    assert decide(state, observation(demand=True), 0, mode="automatic") == "cancel"
    complete(state, "cancel", retry="Kubernetes conflict")
    state.restart()
    assert not state.shutdown_requested
    assert (
        decide(state, observation(ready=False, demand=True), 15, mode="automatic")
        == "restore"
    )
    complete(state, "restore")
    assert decide(state, observation(), 30, mode="automatic", idle_seconds=300) is None
    assert state.phase == "idle"


def test_failed_final_read_restores_instead_of_retrying_shutdown():
    state = State(phase="stopping", pending="stop-worker", shutdown_requested=True)
    complete(state, "stop-worker", retry="Inventory unavailable")
    assert state.phase == "restoring"
    assert not state.shutdown_requested


def test_unknown_power_cannot_extend_uncertain_shutdown_forever():
    state = State(phase="stopping", pending="await-off", deadline=30)
    assert decide(state, observation(power="unknown"), 31, mode="automatic") is None
    assert state.phase == "blocked"


def test_unknown_power_after_restart_still_gets_bounded_window():
    state = State(phase="stopping", pending="await-off")
    state.restart()
    decide(state, observation(power="unknown"), 0, mode="automatic")
    assert state.deadline == 1200
    decide(state, observation(power="unknown"), 1200, mode="automatic")
    assert state.phase == "blocked"
