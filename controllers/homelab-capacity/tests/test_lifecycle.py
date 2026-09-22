from homelab_capacity.lifecycle import Observation, State, complete, decide, observe_off


def test_maintenance_pause_allows_explicit_shutdown_but_prevents_wake():
    state = State(paused=True, shutdown_requested=True)
    assert decide(state, healthy(), 0, mode="automatic") == "quiesce"
    complete(state, "quiesce")
    assert decide(state, healthy(quiesced=True), 15, mode="automatic") == "stop-worker"
    complete(state, "stop-worker")
    state.phase = "off"
    assert (
        decide(state, healthy(power="off", demand=True), 30, mode="automatic") is None
    )
    assert state.paused


def healthy(**changes):
    return Observation(
        **(
            {"power": "on", "identity_ok": True, "ready": True, "complete": True}
            | changes
        )
    )


def test_configured_five_minute_idle_keeps_activity_guards():
    state = State()
    for second in range(0, 300, 15):
        assert (
            decide(state, healthy(), second, mode="automatic", idle_seconds=300) is None
        )
    assert (
        decide(state, healthy(demand=True), 300, mode="automatic", idle_seconds=300)
        is None
    )
    for second in range(315, 615, 15):
        assert (
            decide(state, healthy(), second, mode="automatic", idle_seconds=300) is None
        )
    assert (
        decide(state, healthy(), 615, mode="automatic", idle_seconds=300) == "quiesce"
    )


def test_continuous_idle_then_orderly_shutdown():
    s = State()
    for second in range(0, 1800, 15):
        assert decide(s, healthy(), second, mode="automatic") is None
    assert decide(s, healthy(), 1800, mode="automatic") == "quiesce"
    complete(s, "quiesce")
    assert decide(s, healthy(quiesced=True), 1815, mode="automatic") == "stop-worker"
    complete(s, "stop-worker")
    assert (
        decide(s, healthy(vm_stopped=True, host_empty=False), 1830, mode="automatic")
        is None
    )
    assert (
        decide(s, healthy(vm_stopped=True, host_empty=True), 1845, mode="automatic")
        == "stop-host"
    )
    complete(s, "stop-host")
    assert decide(s, healthy(), 1860, mode="automatic") is None
    off = healthy(power="off", ready=False)
    observe_off(s, off)
    assert decide(s, off, 1875, mode="automatic") is None
    assert s.phase == "off"


def test_gap_unknown_activity_and_reboot_reset_idle():
    s = State()
    decide(s, healthy(), 0, mode="automatic")
    decide(s, healthy(), 2000, mode="automatic")
    assert s.idle_since == 2000
    decide(s, healthy(complete=False), 2015, mode="automatic")
    assert s.idle_since is None
    decide(s, healthy(), 2030, mode="automatic")
    decide(s, healthy(power="unknown"), 2045, mode="automatic")
    assert s.idle_since is None
    s.restart()
    assert s.last_sample is None


def test_new_demand_cancels_before_commit_but_finishes_after():
    s = State(shutdown_requested=True)
    assert decide(s, healthy(), 0, mode="automatic") == "quiesce"
    complete(s, "quiesce")
    assert (
        decide(s, healthy(demand=True, quiesced=True), 15, mode="automatic") == "cancel"
    )
    complete(s, "cancel")
    assert not s.shutdown_requested
    s = State(phase="stopping")
    assert (
        decide(
            s,
            healthy(demand=True, vm_stopped=True, host_empty=True),
            30,
            mode="automatic",
        )
        == "stop-host"
    )


def test_manual_shutdown_armed_pause_persists():
    s = State(phase="off")
    off = healthy(power="off", demand=True)
    assert decide(s, off, 0, mode="automatic") == "wake"
    complete(s, "wake")
    s.paused = True
    s.restart()
    assert s.paused
    s.phase = "off"
    assert decide(s, off, 15, mode="automatic") is None


def test_failure_is_not_retried_and_wrong_identity_never_acts():
    s = State()
    assert (
        decide(
            s, healthy(power="off", demand=True, identity_ok=False), 0, mode="automatic"
        )
        is None
    )
    assert decide(s, healthy(power="off", demand=True), 15, mode="automatic") == "wake"
    complete(s, "wake", error="Unknown write outcome")
    assert decide(s, healthy(power="off", demand=True), 30, mode="automatic") is None
    assert s.phase == "blocked"


def test_observe_and_wake_modes_cannot_shutdown():
    for mode in ["observe", "wake"]:
        s = State(shutdown_requested=True)
        assert decide(s, healthy(), 0, mode=mode) is None
        assert s.pending is None


def test_active_work_and_maintenance_hold_block_manual_shutdown():
    for changes in [{"demand": True}, {"blockers": ["backup"]}, {"complete": False}]:
        s = State(shutdown_requested=True)
        assert decide(s, healthy(**changes), 0, mode="automatic") is None


def test_interrupted_transition_blocks_and_recovery_deadline_bounds_boot():
    s = State(phase="draining", pending="quiesce")
    s.restart()
    assert s.phase == "blocked"
    s = State(phase="waking", deadline=100)
    assert decide(s, healthy(ready=False, demand=True), 100, mode="automatic") is None
    assert s.phase == "blocked"


def test_ai_idle_timer_accumulates_but_waits_for_graceful_ai_exit():
    state = State()
    for second in range(0, 1830, 15):
        assert (
            decide(state, healthy(retirement_ready=False), second, mode="automatic")
            is None
        )
    assert (
        decide(state, healthy(retirement_ready=True), 1830, mode="automatic")
        == "quiesce"
    )


def test_firmware_boot_waits_without_blind_restore_or_early_failure():
    state = State(phase="waking", wake_requested=True, deadline=1200)
    obs = healthy(ready=False, restore_ready=False, complete=False)
    for second in range(0, 900, 15):
        assert decide(state, obs, second, mode="wake") is None
        assert state.phase == "waking"
    assert (
        decide(state, healthy(ready=False, restore_ready=True), 900, mode="wake")
        == "restore"
    )


def test_pending_graceful_quiesce_reconciles_without_resetting_deadline():
    state = State(shutdown_requested=True)
    assert decide(state, healthy(), 0, mode="automatic") == "quiesce"
    complete(state, "quiesce")
    assert decide(state, healthy(quiesced=False), 15, mode="automatic") == "quiesce"
    assert state.deadline == 1200


def test_housekeeping_waits_without_restarting_application_idle_window():
    state = State()
    for second in range(0, 315, 15):
        assert (
            decide(
                state,
                healthy(retirement_ready=False),
                second,
                mode="automatic",
                idle_seconds=300,
            )
            is None
        )
    assert state.idle_since == 0
    assert (
        decide(state, healthy(), 315, mode="automatic", idle_seconds=300) == "quiesce"
    )
    complete(state, "quiesce")
    assert (
        decide(
            state, healthy(quiesced=True, retirement_ready=False), 330, mode="automatic"
        )
        == "quiesce"
    )
    complete(state, "quiesce")
    assert decide(state, healthy(quiesced=True), 345, mode="automatic") == "stop-worker"
