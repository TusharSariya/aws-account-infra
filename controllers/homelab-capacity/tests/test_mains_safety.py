"""Safety contracts across lifecycle, durable interlock and asynchronous outlets."""

from copy import deepcopy
from types import SimpleNamespace

import pytest
from homelab_capacity.coordinator import Coordinator
from homelab_capacity.interlock import Interlock, PowerBlocked
from homelab_capacity.journal import Journal
from homelab_capacity.lifecycle import Observation, State, decide
from homelab_capacity.mains import Mains, validate
from homelab_capacity.platform import Platform
from test_power import controller as imm_controller


class Cloud:
    def __init__(self):
        self.values = [
            {"state": "on", "changed_at": 1, "observed_at": 1} for _ in range(2)
        ]
        self.writes = []
        self.fail = False

    def status(self, outlet):
        return deepcopy(self.values[int(outlet["component_id"])])

    def switch(self, outlet, target):
        self.writes.append((outlet, target))
        if self.fail:
            raise TimeoutError("Lost acknowledgement")
        return "accepted"


def setup(tmp_path):
    journal = Journal(tmp_path / "journal")
    lock = Interlock(tmp_path / "locks", "secondary")
    cloud = Cloud()
    entry = {
        "outlets": [
            {"device_id": "stable-device", "component_id": str(i)} for i in range(2)
        ]
    }
    mains = Mains(entry, journal, "secondary", lock, adapter=cloud)
    return mains, lock, cloud


def test_uncertain_cloud_off_survives_restart_and_blocks_opposite_command(tmp_path):
    mains, lock, cloud = setup(tmp_path)
    mains.shutdown_started("orderly-operation")
    mains.shutdown_acknowledged()
    cloud.fail = True
    with pytest.raises(TimeoutError):
        mains.advance("off")
    assert len(cloud.writes) == 1
    restarted = Mains(
        mains.entry,
        mains.journal,
        mains.host,
        Interlock(tmp_path / "locks", mains.host),
        adapter=cloud,
    )
    for target in ("on", "off"):
        with pytest.raises(PowerBlocked, match="Unresolved"):
            restarted.advance(target)
    restarted.observe()  # cached on is not evidence of cancellation
    assert lock.read()["pending"]
    assert len(cloud.writes) == 1


def test_multi_supply_cut_and_wake_require_fresh_completion_per_outlet(tmp_path):
    mains, lock, cloud = setup(tmp_path)
    mains.shutdown_started("orderly-operation")
    mains.shutdown_acknowledged()
    mains.advance("off")
    at = lock.read()["pending"]["at"]
    cloud.values[0].update(state="off", changed_at=at - 1)
    assert mains.observe() == "mixed"
    assert lock.read()["pending"]  # matching, stale state is insufficient
    cloud.values[0]["changed_at"] = at + 1
    mains.observe()
    assert lock.read()["pending"] is None
    mains.advance("off")
    cloud.values[1].update(state="off", changed_at=lock.read()["pending"]["at"] + 1)
    assert mains.observe(imm_available=False) == "off"
    assert mains.read()["phase"] == "off"
    mains.advance("on")
    assert cloud.writes[-1][1] == "on"
    cloud.values[0].update(state="on", changed_at=lock.read()["pending"]["at"] + 1)
    mains.observe()
    mains.advance("on")
    cloud.values[1].update(state="on", changed_at=lock.read()["pending"]["at"] + 1)
    assert mains.observe(imm_available=True) == "on"
    assert mains.read()["phase"] == "standby"
    assert mains.read()["shutdown"] is None


def test_mapping_change_cannot_resolve_old_command(tmp_path):
    mains, lock, _cloud = setup(tmp_path)
    mains.advance("on")  # all already on, no command
    mains.shutdown_started("operation")
    mains.shutdown_acknowledged()
    mains.advance("off")
    mains.entry = deepcopy(mains.entry)
    mains.entry["outlets"][0]["device_id"] = "replacement"
    with pytest.raises(PowerBlocked, match="mapping changed"):
        mains.observe()
    assert lock.read()["pending"]


def test_mains_requires_acknowledged_shutdown_and_continuous_off_observations(tmp_path):
    mains, _, _ = setup(tmp_path)
    assert not mains.eligible("off", 0)
    mains.shutdown_started("operation")
    assert not mains.eligible("off", 100)
    mains.shutdown_acknowledged()
    assert not mains.eligible("off", 100)
    assert not mains.eligible("off", 130)
    assert mains.eligible("off", 160)
    assert not mains.eligible("unknown", 170)
    assert not mains.eligible("off", 200)
    assert not mains.eligible("off", 300)  # observation gap resets dwell
    assert mains.eligible("off", 360)
    restarted = Mains(
        mains.entry, mains.journal, mains.host, mains.interlock, adapter=mains.adapter
    )
    assert not restarted.eligible("off", 400)


def test_maintenance_survives_restart_and_cannot_acknowledge_uncertain_operation(
    tmp_path,
):
    lock = Interlock(tmp_path, "primary")
    with lock.guard():
        lock.begin("stop-host")
    lock.acquire("firmware", "IMM firmware update")
    lock.acknowledge(settled=True)
    assert not lock.read()["holds"]["firmware"]["acknowledged"]
    lock = Interlock(tmp_path, "primary")
    for _ in range(2):
        with pytest.raises(PowerBlocked), lock.guard():
            pytest.fail("Must not execute")
    lock.settle("stop-host")
    lock.acknowledge(settled=True)
    assert lock.read()["holds"]["firmware"]["acknowledged"]
    with pytest.raises(ValueError):
        lock.release("wrong-token")
    lock.release("firmware")
    with lock.guard():
        pass


def test_standalone_imm_wake_shares_maintenance_protection(tmp_path):
    power, transport = imm_controller(tmp_path, ["power off"])
    power.interlock.acquire("maintenance", "firmware")
    with pytest.raises(RuntimeError, match="maintenance protected"):
        power.ensure_on()
    assert transport.commands == ["power state"]


def test_uncertain_imm_on_cannot_be_replayed_when_still_off(tmp_path):
    power, transport = imm_controller(
        tmp_path, ["power off", TimeoutError(), "power off"]
    )
    with pytest.raises(TimeoutError):
        power.ensure_on()
    with pytest.raises(RuntimeError, match="already in progress"):
        power.ensure_on()
    assert transport.commands == ["power state", "power on", "power state"]


@pytest.mark.parametrize("phase", ["ready", "draining", "stopping", "waking", "off"])
def test_maintenance_blocks_every_lifecycle_stage(phase):
    obs = Observation(
        power="on",
        identity_ok=True,
        complete=True,
        ready=True,
        vm_stopped=True,
        host_empty=True,
        quiesced=True,
        demand=True,
        mains_retire=True,
        maintenance=True,
    )
    state = State(phase=phase, shutdown_requested=True)
    assert decide(state, obs, 0, mode="automatic") is None


def test_committed_shutdown_obeys_late_hold_and_unknown_tasks():
    for changes in (
        {"blockers": ["maintenance"]},
        {"complete": False},
        {"host_empty": False},
    ):
        values = {
            "power": "on",
            "identity_ok": True,
            "complete": True,
            "vm_stopped": True,
            "host_empty": True,
        }
        obs = Observation(**(values | changes))
        assert decide(State(phase="stopping"), obs, 0, mode="automatic") is None


def test_new_demand_skips_cut_and_wakes_imm_after_orderly_shutdown():
    obs = Observation(
        power="off", identity_ok=True, complete=True, demand=True, mains_retire=True
    )
    assert decide(State(phase="stopping"), obs, 0, mode="automatic") == "wake"
    obs.mains, obs.mains_transition = "off", True
    assert decide(State(phase="off"), obs, 0, mode="automatic") == "mains-on"


def test_observe_and_wake_rollouts_cannot_cut_mains():
    obs = Observation(power="off", identity_ok=True, complete=True, mains_retire=True)
    for mode in ("observe", "wake"):
        assert decide(State(), obs, 0, mode=mode) is None


def test_resume_rejects_pending_command_without_preventing_future_observations(
    tmp_path,
):
    coordinator = Coordinator(
        {},
        kube=SimpleNamespace(),
        management=SimpleNamespace(),
        journal=Journal(tmp_path),
    )
    lock = coordinator.interlocks["primary"]
    with lock.guard():
        lock.begin("mains-off")
    coordinator.states["primary"] = State(phase="blocked")
    coordinator.journal.write(
        "primary-command.json", {"id": "resume-1", "action": "resume"}
    )
    coordinator.command("primary")
    assert coordinator.states["primary"].phase == "blocked"
    assert lock.read()["pending"]
    assert coordinator.journal.read("primary-command-result.json")["rejected"]


def test_application_stage_failure_retains_protection_until_observed_complete(tmp_path):
    journal = Journal(tmp_path)
    platform = Platform(SimpleNamespace(), SimpleNamespace(), journal)
    lock = Interlock(tmp_path, "primary")
    platform.interlocks = {"primary": lock}
    obj = {"metadata": {"name": "db", "uid": "db-id"}}

    def crash():
        raise SystemExit("lost process")

    with pytest.raises(SystemExit):
        platform.shutdown_stage("primary", obj, "deployments", crash)
    lock.acquire("firmware", "firmware")
    lock.acknowledge(settled=True)
    assert not lock.read()["holds"]["firmware"]["acknowledged"]
    assert lock.read()["pending"]["action"] == "platform-stage"


def test_duplicate_outlet_assignment_rejected():
    outlet = {"device_id": "one", "component_id": "main"}
    with pytest.raises(ValueError, match="exclusive"):
        validate(
            {
                "mains": {
                    "primary": {"outlets": [outlet]},
                    "secondary": {"outlets": [outlet]},
                }
            }
        )


def test_manual_outlet_change_does_not_trigger_automatic_recovery(tmp_path):
    mains, _, _ = setup(tmp_path)
    mains.journal.write(mains.name, {"phase": "off", "shutdown": "old"})
    with pytest.raises(PowerBlocked, match="Unexpected"):
        mains.observe()


def test_full_cold_cycle_orders_every_lifecycle_effect():
    from homelab_capacity.lifecycle import complete, observe_off

    state = State()
    obs = Observation(power="on", identity_ok=True, complete=True, ready=True)
    effects = []

    def step(now, expected):
        observe_off(state, obs)
        action = decide(state, obs, now, mode="automatic", idle_seconds=300)
        assert action == expected
        if action:
            effects.append(action)
            complete(state, action)

    step(0, None)
    for now in range(15, 300, 15):
        step(now, None)
    step(300, "quiesce")
    obs.quiesced = True
    step(315, "stop-worker")
    obs.ready, obs.vm_stopped, obs.host_empty = False, True, True
    step(330, "stop-host")
    obs.power = "off"
    step(345, None)
    step(375, None)
    obs.mains_retire = True
    step(405, "mains-off")
    obs.mains, obs.mains_transition, obs.mains_retire = "off", True, False
    step(420, None)
    obs.demand = True
    step(435, "mains-on")
    obs.mains, obs.mains_transition = "on", False
    step(450, "wake")
    obs.power = "on"
    step(465, "restore")
    obs.ready = True
    step(480, None)
    assert effects == [
        "quiesce",
        "stop-worker",
        "stop-host",
        "mains-off",
        "mains-on",
        "wake",
        "restore",
    ]


@pytest.mark.parametrize(
    "action",
    ["wake", "stop-worker", "stop-host", "mains-on", "mains-off", "restore", "cancel"],
)
def test_coordinator_final_interlock_blocks_all_power_effects(tmp_path, action):
    coordinator = Coordinator(
        {},
        kube=SimpleNamespace(),
        management=SimpleNamespace(),
        journal=Journal(tmp_path),
    )
    coordinator.interlocks["primary"].acquire("firmware", "firmware update")
    # No management method is even available: reaching one would fail the test.
    with pytest.raises(PowerBlocked, match="Maintenance"):
        coordinator.effect("primary", action, {})


def test_maintenance_arriving_between_application_stages_prevents_next_stage(tmp_path):
    journal = Journal(tmp_path)
    platform = Platform(SimpleNamespace(), SimpleNamespace(), journal)
    lock = Interlock(tmp_path, "primary")
    platform.interlocks = {"primary": lock}
    obj = {"metadata": {"name": "db", "uid": "db-id"}}

    def first():
        lock.acquire("firmware", "maintenance requested while stage settles")
        return True

    assert platform.shutdown_stage("primary", obj, "deployments", first)
    with pytest.raises(PowerBlocked):
        platform.shutdown_stage(
            "primary", obj, "deployments", lambda: pytest.fail("second stage ran")
        )


def test_wake_invalidates_old_shutdown_authorization(tmp_path):
    mains, _, _ = setup(tmp_path)
    mains.shutdown_started("old-operation")
    mains.shutdown_acknowledged()
    assert not mains.eligible("off", 0)
    assert mains.eligible("off", 60)
    mains.invalidate_shutdown()
    assert not mains.eligible("off", 120)
    with pytest.raises(PowerBlocked, match="shutdown evidence"):
        mains.advance("off")


def commissioned(tmp_path):
    mains, lock, cloud = setup(tmp_path)
    mains.entry["mode"] = "commissioning"
    cloud.health = lambda: dict(
        remaining_seconds=8000,
        refresh_uncertain=False,
        renewable=False,
        refresh_verified=False,
    )
    mains.journal.write(
        "secondary-mains-mapping.json",
        {
            "host": "secondary",
            "outlets": mains.entry["outlets"],
            "evidence": "controlled physical mapping test",
        },
    )
    mains.start_commission()
    return mains, lock, cloud


def test_commission_requires_ready_before_cut_and_records_complete_cycle(tmp_path):
    mains, _, _ = commissioned(tmp_path)
    state = State()
    with pytest.raises(PowerBlocked):
        mains.may_cut()
    mains.commission_tick(state, Observation(ready=True))
    mains.may_cut()
    mains.journal.write(mains.name, {"phase": "off", "shutdown": "orderly-1"})
    mains.commission_tick(state, Observation(mains="off"))
    assert state.wake_requested
    assert not mains.journal.read("secondary-mains-acceptance.json", {})
    mains.journal.write(mains.name, {"phase": "standby"})
    mains.commission_tick(state, Observation(ready=True))
    receipt = mains.journal.read("secondary-mains-acceptance.json")
    assert receipt["shutdown_operation"] == "orderly-1"
    assert receipt["cycle_id"] == mains.session()["id"]
    assert mains.session()["stage"] == "complete"
    with pytest.raises(PowerBlocked):
        mains.may_cut()  # one session never grants perpetual permission


@pytest.mark.parametrize("expired", [False, True])
def test_disabled_or_expired_session_restores_ac_without_cut_permission(
    tmp_path, expired
):
    mains, _, _ = commissioned(tmp_path)
    if expired:
        mains.clock = lambda: mains.session()["expires_at"] + 1
    else:
        mains.entry["mode"] = "disabled"
    obs = Observation(
        power="off", identity_ok=True, complete=True, mains="off", mains_transition=True
    )
    state = State(phase="off")
    obs.restore_mains = mains.commission_tick(state, obs)
    assert obs.restore_mains
    assert decide(state, obs, 0, mode="automatic") == "mains-on"
    with pytest.raises(PowerBlocked):
        mains.may_cut()


def test_last_cloud_confirmation_needs_physical_loss(tmp_path):
    mains, lock, cloud = setup(tmp_path)
    mains.entry["outlets"] = mains.entry["outlets"][:1]
    mains.shutdown_started("operation")
    mains.shutdown_acknowledged()
    mains.advance("off")
    cloud.values[0].update(state="off", changed_at=lock.read()["pending"]["at"] + 1)
    mains.observe(imm_available=True)
    assert lock.read()["pending"]
    assert mains.read()["phase"] == "cutting"
    mains.observe(imm_available=False)
    assert lock.read()["pending"] is None
    assert mains.read()["phase"] == "off"


def test_automatic_mode_refuses_temporary_pat_after_completed_cycle(tmp_path):
    mains, _, _ = commissioned(tmp_path)
    mains.entry["mode"] = "automatic"
    with pytest.raises(PowerBlocked, match="renewable OAuth"):
        mains.may_cut()


@pytest.mark.parametrize("remaining", [8000, None])
def test_explicit_temporary_authorization_preserves_cycle_and_site_guards(tmp_path, remaining):
    mains, _, cloud = commissioned(tmp_path)
    health = cloud.health()
    cloud.health = lambda: health | {"remaining_seconds": remaining}
    mains.entry.update(mode="automatic", allow_temporary_credentials=True)
    with pytest.raises(PowerBlocked, match="cold-cycle"):
        mains.may_cut()
    mains.journal.write(
        "secondary-mains-acceptance.json",
        {
            "host": "secondary",
            "outlets": mains.entry["outlets"],
            "cycle_id": "verified-cycle",
        },
    )
    with pytest.raises(PowerBlocked, match="Site review"):
        mains.may_cut()
    mains.journal.write(
        "secondary-mains-site.json",
        {
            "outlets": mains.entry["outlets"],
            **{
                k: {"evidence": "verified", "checked_at": 1}
                for k in (
                    "electrical_rating",
                    "exclusive_load",
                    "no_competing_automation",
                )
            },
        },
    )
    mains.may_cut()


@pytest.mark.parametrize("remaining,uncertain", [(3599, False), (8000, True), (None, True)])
def test_temporary_authorization_never_bypasses_expiry_or_uncertainty(
    tmp_path, remaining, uncertain
):
    mains, _, cloud = commissioned(tmp_path)
    mains.entry.update(mode="automatic", allow_temporary_credentials=True)
    cloud.health = lambda: dict(
        remaining_seconds=remaining,
        refresh_uncertain=uncertain,
        renewable=False,
        refresh_verified=False,
    )
    with pytest.raises(PowerBlocked, match="Authorization unhealthy"):
        mains.may_cut()
