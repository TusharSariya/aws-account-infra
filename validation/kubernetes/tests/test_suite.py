import copy
import json
import re
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core import Blocked, Cluster, LABEL, Run, load_profile, metrics, quantity
from scenarios import admission, burner_config, cancel, job, queueing
from suite import main


class SuiteTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.p = load_profile(ROOT / "profiles/pilot.json")
        self.r = Run(self.p, self.tmp.name, "kv-0123456789abcdef", cluster=Mock())
        self.r.uid = "cluster-uid"

    def test_profile_budgets(self):
        self.assertEqual(quantity("250m"), quantity("0.25"))
        self.assertEqual(quantity("128Mi"), 134217728)
        for val in ("-1", "NaN", "infinity", "1;echo secret"):
            with self.assertRaises(ValueError):
                quantity(val)

    def test_invalid_load_rejected_before_cluster_access(self):
        p = copy.deepcopy(self.p)
        p["load"]["bursts"] = [10000]
        filename = Path(self.tmp.name) / "profile.json"
        filename.write_text(json.dumps(p))
        with self.assertRaises(ValueError):
            load_profile(filename)

    def test_job_is_suspended_owned_and_sandboxed(self):
        obj = job(self.r, "probe")
        self.assertTrue(obj["spec"]["suspend"])
        self.assertEqual(obj["metadata"]["labels"][LABEL], self.r.id)
        spec = obj["spec"]["template"]["spec"]
        self.assertFalse(spec["automountServiceAccountToken"])
        self.assertEqual(spec["nodeSelector"]["prototype.homelab/slot"], "primary")
        self.assertEqual(spec["containers"][0]["resources"]["requests"]["cpu"], "250m")

    def test_burner_never_deletes_namespaces_or_preloads_daemonsets(self):
        _, filename = burner_config(self.r, 16)
        cfg = json.loads(filename.read_text())
        self.assertFalse(cfg["global"]["gc"])
        j = cfg["jobs"][0]
        for key in (
            "cleanup",
            "gc",
            "namespacedIterations",
            "preLoadImages",
        ):
            self.assertFalse(j[key])
        self.assertTrue(j["waitWhenFinished"])
        manifest = json.loads(Path(j["objects"][0]["objectTemplate"]).read_text())
        self.assertIn("{{.Iteration}}", manifest["metadata"]["name"])
        self.assertEqual(
            manifest["spec"]["template"]["metadata"]["labels"]["kube-burner.io/runid"],
            "{{.RunID}}",
        )
        self.assertEqual(manifest["metadata"]["namespace"], "prototype-slot")

    def test_foreign_and_namespace_cleanup_protection(self):
        c = Cluster(self.p)
        c.call = Mock()
        obj = {"kind": "Job", "metadata": {"labels": {LABEL: "foreign"}}}
        with self.assertRaisesRegex(RuntimeError, "foreign"):
            c.delete_owned(obj, self.r.id)
        obj = {"kind": "Namespace", "metadata": {"labels": {LABEL: self.r.id}}}
        with self.assertRaisesRegex(RuntimeError, "allowlist"):
            c.delete_owned(obj, self.r.id)
        c.call.assert_not_called()

    def test_delete_has_server_side_generation_preconditions(self):
        c = Cluster(self.p)
        c.call = Mock()
        obj = job(self.r, "delete")
        obj["metadata"].update(uid="original-uid", resourceVersion="7")
        c.delete_owned(obj, self.r.id)
        options = json.loads(c.call.call_args.kwargs["data"])
        self.assertEqual(
            options["preconditions"], {"uid": "original-uid", "resourceVersion": "7"}
        )
        self.assertIn("/namespaces/prototype-slot/jobs/", c.call.call_args.args[2])

    def test_changed_cluster_prevents_cleanup(self):
        self.r.c.identity.side_effect = Blocked("Cluster UID changed")
        with self.assertRaises(Blocked):
            self.r.cleanup()
        self.r.c.delete_owned.assert_not_called()

    def test_cleanup_failure_and_retry_are_recorded(self):
        self.r.c.get.side_effect = RuntimeError("API unavailable")
        self.r.execute("cleanup", lambda r: r.cleanup())
        self.assertEqual(self.r.results[-1]["status"], "failed")
        self.r.c.get.side_effect = None
        self.r.c.get.return_value = []
        self.r.execute("cleanup-retry", lambda r: r.cleanup())
        self.assertEqual(self.r.results[-1]["status"], "passed")
        self.assertEqual(
            self.r.report(), 1
        )  # Retry never erases prior failure evidence.

    def test_blocked_and_deferred_are_not_junit_passes(self):
        self.r.results = [
            {"name": "missing", "status": "blocked", "detail": "paused"},
            {"name": "future", "status": "deferred", "detail": "needs adapter"},
        ]
        self.assertEqual(self.r.report(), 1)
        xml = ET.parse(Path(self.tmp.name) / "junit.xml")
        self.assertIsNotNone(xml.find(".//error"))
        self.assertIsNotNone(xml.find(".//skipped"))
        self.assertEqual(
            json.loads((Path(self.tmp.name) / "report.json").read_text())["status"],
            "incomplete",
        )

    def test_interruption_records_failed_scenario(self):
        with self.assertRaises(KeyboardInterrupt):
            self.r.execute(
                "cancel", lambda r: (_ for _ in ()).throw(KeyboardInterrupt())
            )
        self.assertEqual(self.r.results[-1]["status"], "failed")

    def test_paused_hosts_never_resumed(self):
        root = Path(self.tmp.name)
        for slot in self.p["slots"].values():
            slot["state"] = str(root)
        (root / "maintenance").touch()
        with self.assertRaisesRegex(Blocked, "paused"):
            self.r.slots(["primary"])
        self.assertTrue((root / "maintenance").exists())

    def replay(self, sequence):
        now = [0]
        node = {
            "metadata": {
                "uid": "n",
                "name": "worker",
                "labels": {
                    "prototype.homelab/pool": "workers",
                    "prototype.homelab/slot": "primary",
                },
            },
            "spec": {},
            "status": {
                "allocatable": {"cpu": "2", "memory": "2Gi", "ephemeral-storage": "2Gi"}
            },
        }
        obj = job(self.r, "replay")
        obj["metadata"]["uid"] = "j"

        def sample():
            row = sequence.pop(0)
            now[0] = row["elapsed"]
            self.r.c.get.return_value = {
                "status": {
                    "flavorsReservation": [
                        {
                            "resources": [
                                {
                                    "name": "cpu",
                                    "total": "3" if row.get("quota_full") else "0",
                                }
                            ]
                        }
                    ]
                }
            }
            j, n = copy.deepcopy(obj), copy.deepcopy(node)
            j["spec"]["suspend"] = row["suspend"]
            j["status"] = {
                "conditions": [
                    {
                        "type": "Complete",
                        "status": str(row["complete"]).lower().capitalize(),
                    }
                ]
            }
            n["status"]["conditions"] = [
                {"type": "Ready", "status": str(row["node_ready"]).lower().capitalize()}
            ]
            return {"jobs": [j], "nodes": [n], "pods": [], "workloads": []}

        self.r.sample = sample
        self.r.c.call.return_value = '{"items": []}'
        self.r.c.get.return_value = {"status": {"flavorsReservation": []}}
        with patch("time.monotonic", side_effect=lambda: now[0]), patch("time.sleep"):
            return admission(self.r, [obj["metadata"]["name"]])

    def test_recorded_delayed_capacity_then_admission(self):
        sequence = json.loads((ROOT / "tests/fixtures/admission.json").read_text())
        self.assertTrue(self.replay(sequence))

    def test_capacity_timeout(self):
        with self.assertRaisesRegex(TimeoutError, "Capacity readiness"):
            self.replay(
                [
                    {
                        "elapsed": 901,
                        "node_ready": False,
                        "suspend": True,
                        "complete": False,
                    }
                ]
            )

    def test_admission_timeout_starts_when_capacity_usable(self):
        with self.assertRaisesRegex(TimeoutError, "Admission after usable capacity"):
            self.replay(
                [
                    {
                        "elapsed": 899,
                        "node_ready": True,
                        "suspend": True,
                        "complete": False,
                    },
                    {
                        "elapsed": 1020,
                        "node_ready": True,
                        "suspend": True,
                        "complete": False,
                    },
                ]
            )

    def test_cancel_waits_for_workload_and_pod_removal(self):
        obj = job(self.r, "cancel")
        obj["metadata"].update(uid="job-uid", resourceVersion="1")
        workload = {"metadata": {"ownerReferences": [{"uid": "job-uid"}]}}
        self.r.sample = Mock(
            side_effect=[
                {"jobs": [], "pods": [], "workloads": [workload]},
                {"jobs": [], "pods": [], "workloads": []},
            ]
        )
        with patch("time.sleep"):
            cancel(self.r, obj)
        self.assertEqual(self.r.sample.call_count, 2)

    def test_quota_fill_checks_budget_before_creating(self):
        self.p["budgets"]["max_jobs"] = 4
        self.r.create = Mock()
        with self.assertRaises(Blocked):
            queueing(self.r)
        self.r.create.assert_not_called()

    def test_requested_missing_prerequisite_is_blocked(self):
        self.r.execute(
            "storage",
            lambda _: (_ for _ in ()).throw(Blocked("Missing disposable class")),
        )
        self.assertEqual(self.r.results[0]["status"], "blocked")
        self.assertEqual(self.r.report(), 1)

    def test_unknown_scenario_rejected(self):
        with self.assertRaises(SystemExit):
            main(["run", "--scenarios", "typo"])

    def test_metrics_deduplicate_completed_jobs(self):
        j = {
            "metadata": {"uid": "j"},
            "status": {"conditions": [{"type": "Complete", "status": "True"}]},
        }
        events = [{"kind": "observation", "elapsed": t, "jobs": [j]} for t in (0, 10)]
        result = metrics(events)
        self.assertEqual(result["completed_jobs"], 1)
        self.assertEqual(result["jobs_per_second"], 0.1)

    def test_live_recording_preserves_server_timing_and_placement(self):
        from core import resource_timings

        events = json.loads((ROOT / "tests/fixtures/live-smoke.json").read_text())
        result = resource_timings(events)
        self.assertTrue(any(x.get("Admitted") for x in result))
        self.assertTrue(any(x.get("Complete") for x in result))
        self.assertTrue(any(x.get("Ready") and x.get("node") for x in result))
        self.assertEqual(metrics(events)["completed_jobs"], 1)

    def test_recorded_worker_recreation_checks_both_identities(self):
        from scenarios import assert_fresh_worker

        record = json.loads(
            (ROOT / "tests/fixtures/worker-recreation.json").read_text()
        )

        def node(info):
            return {
                "metadata": {"uid": info["uid"]},
                "status": {"nodeInfo": {"systemUUID": info["systemUUID"]}},
            }

        before, after = node(record["before"]), node(record["after"])
        assert_fresh_worker(before, after)
        with self.assertRaises(AssertionError):
            assert_fresh_worker(before, before)
        after["status"] = before["status"]
        with self.assertRaisesRegex(AssertionError, "hardware"):
            assert_fresh_worker(before, after)

    def test_retirement_sequence_rejects_early_commit_and_foreign_generation(self):
        from scenarios import retirement_ready

        state = {"phase": "shutdown-committed", "uid": "old"}
        self.assertFalse(retirement_ready(state, "new", 0, 316.3, 300))
        with self.assertRaisesRegex(AssertionError, "idle window"):
            retirement_ready(state, "old", 0, 299, 300)
        self.assertEqual(retirement_ready(state, "old", 0, 316.3, 300), state)
        with self.assertRaisesRegex(AssertionError, "blocked"):
            retirement_ready({"phase": "blocked"}, "old", 0, 600, 300)

    def test_interrupted_main_still_runs_final_cleanup(self):
        def preflight(run):
            run.uid = "cluster-uid"

        with (
            patch("suite.Run.preflight", preflight),
            patch("suite.Run.cleanup") as cleanup,
            patch.dict(
                "suite.SCENARIOS",
                {"smoke": lambda _: (_ for _ in ()).throw(KeyboardInterrupt())},
            ),
            patch("suite.path", return_value=Path(self.tmp.name)),
        ):
            code = main(["run", "--output", self.tmp.name, "--scenarios", "services"])
        self.assertEqual(code, 1)
        cleanup.assert_called_once()
        result = json.loads(
            next(Path(self.tmp.name).glob("kv-*/report.json")).read_text()
        )
        self.assertTrue(
            any(
                r["name"] == "services" and r["status"] == "blocked"
                for r in result["results"]
            )
        )
        self.assertTrue(
            any(
                r["name"] == "final-cleanup" and r["status"] == "passed"
                for r in result["results"]
            )
        )

    def test_zero_worker_proof_uses_live_smoke_from_same_run(self):
        from scenarios import from_zero

        self.r.initial_workers = []
        self.r.initial_slots = {"primary": {"paused": False, "desired": {"target": 0}}}
        self.r.smoke_snapshot = {
            "nodes": [{"metadata": {"uid": "fresh"}}],
            "pods": [{}],
        }
        from_zero(self.r)
        self.assertEqual(self.r.events[-1]["kind"], "zero-worker-proof")

    def test_state_contains_exact_cleanup_profile(self):
        self.r.state()
        saved = json.loads((Path(self.tmp.name) / "profile.json").read_text())
        self.assertEqual(saved, self.p)

    def test_interrupted_burner_is_terminated(self):
        from scenarios import burst

        self.r.slots = Mock()
        self.r.sample = Mock(side_effect=KeyboardInterrupt())
        proc = Mock()
        proc.poll.return_value = None
        with patch("scenarios.subprocess.Popen", return_value=proc):
            with self.assertRaises(KeyboardInterrupt):
                burst(self.r, 4)
        proc.terminate.assert_called_once()
        proc.wait.assert_called_once()

    def test_quota_wait_is_not_an_admission_timeout(self):
        self.assertTrue(
            self.replay(
                [
                    {
                        "elapsed": 0,
                        "node_ready": True,
                        "suspend": True,
                        "complete": False,
                        "quota_full": True,
                    },
                    {
                        "elapsed": 200,
                        "node_ready": True,
                        "suspend": True,
                        "complete": False,
                        "quota_full": True,
                    },
                    {
                        "elapsed": 300,
                        "node_ready": True,
                        "suspend": False,
                        "complete": False,
                    },
                    {
                        "elapsed": 305,
                        "node_ready": True,
                        "suspend": False,
                        "complete": True,
                    },
                ]
            )
        )

    def test_run_label_alone_does_not_authorize_foreign_named_resource(self):
        obj = job(self.r, "owned")
        obj["metadata"]["name"] = "retained-marker"
        c = Cluster(self.p)
        c.call = Mock()
        with self.assertRaisesRegex(RuntimeError, "name is not owned"):
            c.delete_owned(obj, self.r.id)
        c.call.assert_not_called()

    def test_generator_error_does_not_wait_for_capacity_timeout(self):
        proc = Mock()
        proc.poll.return_value = 1
        self.r.sample = Mock()
        with self.assertRaisesRegex(AssertionError, "generation failed"):
            admission(self.r, ["missing"], generator=proc)
        self.r.sample.assert_not_called()

    def test_cleanup_retries_status_conflict_on_same_uid(self):
        obj = job(self.r, "conflict")
        obj["metadata"].update(uid="original", resourceVersion="1")
        refreshed = copy.deepcopy(obj)
        refreshed["metadata"]["resourceVersion"] = "2"
        c = Cluster(self.p)
        c.call = Mock(
            side_effect=[
                RuntimeError("Error from server (Conflict): changed status"),
                "",
            ]
        )
        c.get = Mock(return_value=refreshed)
        c.delete_owned(obj, self.r.id)
        options = json.loads(c.call.call_args.kwargs["data"])
        self.assertEqual(
            options["preconditions"], {"uid": "original", "resourceVersion": "2"}
        )
        self.assertEqual(c.call.call_count, 2)

    def test_cleanup_conflict_never_retries_replacement_or_foreign_owner(self):
        for change in ({"uid": "replacement"}, {"labels": {LABEL: "foreign"}}):
            obj = job(self.r, "conflict")
            obj["metadata"].update(uid="original", resourceVersion="1")
            refreshed = copy.deepcopy(obj)
            refreshed["metadata"].update(change)
            c = Cluster(self.p)
            c.call = Mock(
                side_effect=RuntimeError("Error from server (Conflict): changed status")
            )
            c.get = Mock(return_value=refreshed)
            with self.assertRaises(RuntimeError):
                c.delete_owned(obj, self.r.id)
            self.assertEqual(c.call.call_count, 1)

    def test_cleanup_tolerates_garbage_collection_race(self):
        obj = job(self.r, "gone")
        obj["metadata"].update(uid="original", resourceVersion="1")
        c = Cluster(self.p)
        c.call = Mock(
            side_effect=RuntimeError("Error from server (NotFound): already deleted")
        )
        c.delete_owned(obj, self.r.id)

    def test_cleanup_conflict_retry_is_bounded(self):
        obj = job(self.r, "conflict")
        obj["metadata"].update(uid="original", resourceVersion="1")
        c = Cluster(self.p)
        c.call = Mock(
            side_effect=RuntimeError("Error from server (Conflict): continuous updates")
        )
        c.get = Mock(return_value=obj)
        with self.assertRaises(RuntimeError):
            c.delete_owned(obj, self.r.id)
        self.assertEqual(c.call.call_count, 5)

    def test_storage_refuses_available_existing_volume_before_creating_claim(self):
        from scenarios import storage

        self.p["storage"]["class"] = "disposable"
        self.r.slots = Mock()
        self.r.c.get.side_effect = [
            {"reclaimPolicy": "Delete"},
            [
                {
                    "metadata": {"uid": "old"},
                    "spec": {"storageClassName": "disposable"},
                    "status": {"phase": "Available"},
                }
            ],
        ]
        self.r.create = Mock()
        with self.assertRaisesRegex(Blocked, "pre-existing"):
            storage(self.r)
        self.r.create.assert_not_called()

    def test_storage_preserves_existing_or_retained_binding(self):
        self.r.initial_volume_uids = ["old"]
        claim = {"metadata": {"uid": "claim"}, "spec": {"volumeName": "pv"}}
        for uid, policy in (("old", "Delete"), ("new", "Retain")):
            self.r.c.get.return_value = {
                "metadata": {"uid": uid},
                "spec": {
                    "claimRef": {"uid": "claim"},
                    "persistentVolumeReclaimPolicy": policy,
                },
            }
            with self.assertRaisesRegex(RuntimeError, "preserving claim and data"):
                self.r.validate_claim(claim)
        self.r.c.call.assert_not_called()

    def test_storage_records_fresh_volume_for_interrupted_cleanup(self):
        self.r.initial_volume_uids = ["old"]
        claim = {"metadata": {"uid": "claim"}, "spec": {"volumeName": "pv"}}
        self.r.c.get.return_value = {
            "metadata": {"uid": "new"},
            "spec": {
                "claimRef": {"uid": "claim"},
                "persistentVolumeReclaimPolicy": "Delete",
            },
        }
        self.r.validate_claim(claim)
        state = json.loads((Path(self.tmp.name) / "run.json").read_text())
        self.assertEqual(state["allocated_volumes"], [{"name": "pv", "uid": "new"}])
        self.assertEqual(state["initial_volume_uids"], ["old"])

    def test_storage_cleanup_without_inventory_fails_closed(self):
        with self.assertRaisesRegex(RuntimeError, "No initial volume inventory"):
            self.r.validate_claim({"spec": {}})

    def test_delete_guard_rechecks_binding_after_status_conflict(self):
        obj = job(self.r, "conflict")
        obj["metadata"].update(uid="original", resourceVersion="1")
        c = Cluster(self.p)
        c.call = Mock(
            side_effect=RuntimeError("Error from server (Conflict): binding changed")
        )
        c.get = Mock(return_value=obj)
        guard = Mock(side_effect=[None, RuntimeError("Unsafe new binding")])
        with self.assertRaisesRegex(RuntimeError, "Unsafe new binding"):
            c.delete_owned(obj, self.r.id, guard=guard)
        self.assertEqual(c.call.call_count, 1)

    def test_load_accounts_for_scratch_page_cache_under_memory_limit(self):
        from scenarios import load_script

        for memory in ("32Mi", "128Mi", "256Mi"):
            self.p["load"]["memory"] = memory
            script = load_script(self.r)
            counts = [int(n) for n in re.findall(r"count=(\d+)", script)]
            self.assertEqual(len(counts), 2)
            self.assertLessEqual(sum(counts) * 1024, int(quantity(memory)) * 3 // 4)
            self.assertLessEqual(
                counts[0] * 1024, int(quantity(self.p["load"]["scratch"]))
            )


if __name__ == "__main__":
    unittest.main()
