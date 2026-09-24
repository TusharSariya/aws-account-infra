import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1]))
from store import Store
import pytest


def profile(name="gpu", kind="gpu", priority=0, generation="node/boot/pod"):
    return dict(
        id=name,
        kind=kind,
        desktop=name == "desktop",
        priority=priority,
        model="qwen",
        healthy=True,
        generation=generation,
    )


@pytest.fixture
def store(tmp_path):
    return Store(tmp_path / "requests.db")


def submit(s, **kw):
    return s.submit({"model": "qwen", "messages": []}, **kw)


def test_busy_gpu_prefers_desktop_then_server_and_required_waits(store):
    submit(store, policy="gpu-required")
    assert store.claim([profile()])[0]["backend"] == "gpu"
    required = submit(store, policy="gpu-required")
    preferred = submit(store)
    cpu = submit(store, policy="cpu-only")
    found = store.claim(
        [profile(), profile("desktop", "cpu", 1), profile("server", "cpu", 2)]
    )
    assert {r["backend"] for r in found} == {"desktop", "server"}
    assert store.get(preferred["id"])["backend"] == "desktop"
    assert store.get(cpu["id"])["backend"] == "server"
    assert store.get(required["id"])["state"] == "queued"


def test_fairness_survives_restart(store):
    for _ in range(5):
        submit(store, lane="live")
        submit(store, lane="batch")
    lanes = []
    for _ in range(8):
        r = store.claim([profile()])[0]
        lanes.append(r["lane"])
        store.complete(r["id"], r["attempt"], {})
        store = Store(store.path)
    assert lanes == ["live", "live", "live", "batch", "live", "live", "batch", "batch"]


def test_uncertainty_reserves_slot_until_real_fence(store):
    r = submit(store, retry_safe=True)
    store.claim([profile()])
    store.recover()
    store.fenced_by_reboot([profile(generation="node/boot/new-pod")])
    assert store.claim([profile()]) == []
    store.fenced_by_reboot([profile(generation="node/new-boot/new-pod")])
    assert store.claim([profile()])[0]["attempt"] == 2
    assert not store.complete(r["id"], 1, {"stale": True})


def test_retry_limit_and_never_retry_streams(store):
    r = submit(store, retry_safe=True)
    for attempt in range(1, 4):
        assert store.claim([profile()])[0]["attempt"] == attempt
        store.failed(r["id"], attempt, "failed", terminated=True)
    assert store.get(r["id"])["state"] == "failed"
    r = submit(store, lane="live", stream=True, retry_safe=True)
    store.claim([profile()])
    store.failed(r["id"], 1, "interrupted", terminated=True)
    assert store.get(r["id"])["state"] == "interrupted"


def test_idempotency_publication_and_admission_timeout(store):
    r = submit(store, request_id="same", lane="live", now=100)
    assert submit(store, request_id="same", lane="live", now=101)["id"] == r["id"]
    with pytest.raises(ValueError):
        submit(store, request_id="same", policy="cpu-only")
    assert store.claim([profile()], now=131) == []
    assert store.get("same")["state"] == "expired"
    r = submit(store)
    store.claim([profile()])
    assert store.complete(r["id"], 1, {"first": True})
    assert not store.complete(r["id"], 1, {"duplicate": True})


def test_additional_gpu_backends_each_get_one_slot(store):
    for _ in range(4):
        submit(store, policy="gpu-required")
    assert len(store.claim([profile("one"), profile("two")])) == 2
    assert store.claim([profile("one"), profile("two")]) == []


def test_queue_and_retention_bounds(tmp_path):
    s = Store(tmp_path / "s.db", limit=1, retention_limit=2)
    submit(s)
    with pytest.raises(OverflowError):
        submit(s)
    r = s.claim([profile()])[0]
    s.complete(r["id"], 1, {})
    submit(s)
    r = s.claim([profile()])[0]
    s.complete(r["id"], 1, {})
    with pytest.raises(OverflowError):
        submit(s)


def test_simultaneous_claims_cannot_double_book_backend(store):
    from concurrent.futures import ThreadPoolExecutor

    for _ in range(10):
        submit(store)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.claim([profile()]), range(8)))
    assert sum(len(result) for result in results) == 1


def test_replacement_node_is_not_proof_of_fencing(store):
    request = submit(store, retry_safe=True)
    store.claim([profile()])
    store.recover()
    store.fenced_by_reboot([profile(generation="replacement-node/new-boot/new-pod")])
    assert store.get(request["id"])["state"] == "uncertain"
