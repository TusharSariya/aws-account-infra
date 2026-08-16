#!/usr/bin/env python3
"""Serialized, checkpointed reconciliation for catalog external providers.

Live execution is intentionally local. GitHub-hosted CI validates static inputs only.
No provider credential is accepted as an argument or written to the journal.
"""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Protocol


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "catalog.json"
GATES = ROOT / "catalog" / "external-provider-gates.json"
TOFU_ROOT = ROOT / "live" / "external" / "supabase"
STAGES = ("validated", "planned", "applied", "recorded", "complete")


class ReconcileError(RuntimeError):
    pass


class Journal(Protocol):
    def acquire(self, binding_id: str, owner: str, lease_seconds: int) -> dict: ...
    def checkpoint(self, binding_id: str, owner: str, values: dict) -> dict: ...
    def release(self, binding_id: str, owner: str) -> None: ...


class FileJournal:
    """Local/fake journal with an advisory file lock for deterministic tests."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock_path = path.with_suffix(path.suffix + ".lock")

    @contextlib.contextmanager
    def _locked(self):
        with self.lock_path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield

    def _read(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text(encoding="utf-8"))

    def _write(self, value: dict) -> None:
        payload = json.dumps(value, indent=2, sort_keys=True) + "\n"
        fd, temporary = tempfile.mkstemp(prefix="journal-", dir=self.path.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def acquire(self, binding_id: str, owner: str, lease_seconds: int) -> dict:
        now = int(time.time())
        with self._locked():
            state = self._read()
            item = state.get(binding_id, {"binding_id": binding_id})
            if item.get("lock_owner") not in (None, owner) and item.get("lock_expires_at", 0) >= now:
                raise ReconcileError(f"binding {binding_id} is locked by another reconciler")
            item.update({"lock_owner": owner, "lock_expires_at": now + lease_seconds})
            state[binding_id] = item
            self._write(state)
            return item

    def checkpoint(self, binding_id: str, owner: str, values: dict) -> dict:
        with self._locked():
            state = self._read()
            item = state.get(binding_id)
            if not item or item.get("lock_owner") != owner:
                raise ReconcileError(f"reconciler no longer owns lock for {binding_id}")
            item.update(values)
            item["updated_at"] = int(time.time())
            state[binding_id] = item
            self._write(state)
            return item

    def release(self, binding_id: str, owner: str) -> None:
        with self._locked():
            state = self._read()
            item = state.get(binding_id)
            if item and item.get("lock_owner") == owner:
                item.pop("lock_owner", None)
                item.pop("lock_expires_at", None)
                state[binding_id] = item
                self._write(state)


class DynamoDBJournal:
    """Production journal. The table uses binding_id as its string partition key."""

    def __init__(self, table_name: str, region: str):
        import boto3

        self.table = boto3.resource("dynamodb", region_name=region).Table(table_name)

    def acquire(self, binding_id: str, owner: str, lease_seconds: int) -> dict:
        from boto3.dynamodb.conditions import Attr

        now = int(time.time())
        try:
            response = self.table.update_item(
                Key={"binding_id": binding_id},
                UpdateExpression="SET lock_owner = :owner, lock_expires_at = :expiry",
                ExpressionAttributeValues={":owner": owner, ":expiry": now + lease_seconds},
                ConditionExpression=(
                    Attr("lock_owner").not_exists()
                    | Attr("lock_owner").eq(owner)
                    | Attr("lock_expires_at").lt(now)
                ),
                ReturnValues="ALL_NEW",
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException as exc:
            raise ReconcileError(f"binding {binding_id} is locked by another reconciler") from exc
        return response["Attributes"]

    def checkpoint(self, binding_id: str, owner: str, values: dict) -> dict:
        from boto3.dynamodb.conditions import Attr

        names = {f"#f{index}": key for index, key in enumerate(values)}
        encoded = {f":v{index}": value for index, value in enumerate(values.values())}
        names["#updated_at"] = "updated_at"
        encoded[":updated_at"] = int(time.time())
        assignments = [
            f"{name} = :v{index}" for index, name in enumerate(names) if name != "#updated_at"
        ]
        assignments.append("#updated_at = :updated_at")
        response = self.table.update_item(
            Key={"binding_id": binding_id},
            UpdateExpression="SET " + ", ".join(assignments),
            ExpressionAttributeNames=names,
            ExpressionAttributeValues=encoded,
            ConditionExpression=Attr("lock_owner").eq(owner),
            ReturnValues="ALL_NEW",
        )
        return response["Attributes"]

    def release(self, binding_id: str, owner: str) -> None:
        from boto3.dynamodb.conditions import Attr

        try:
            self.table.update_item(
                Key={"binding_id": binding_id},
                UpdateExpression="REMOVE lock_owner, lock_expires_at",
                ConditionExpression=Attr("lock_owner").eq(owner),
            )
        except self.table.meta.client.exceptions.ConditionalCheckFailedException:
            return


class FakeAdapter:
    def __init__(self, state_dir: Path):
        self.state_dir = state_dir
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def plan(self, service: dict, purge: bool) -> None:
        return None

    def apply(self, service: dict, purge: bool) -> dict:
        path = self.state_dir / f"{service['service']['uid']}.json"
        if purge:
            path.unlink(missing_ok=True)
            return {"purged": True}
        target = service["external_services"]["supabase"]
        result = {
            "project_ref": target.get("project_ref")
            or hashlib.sha256(service["service"]["uid"].encode()).hexdigest()[:20],
            "project_name": target["project_name"],
        }
        path.write_text(json.dumps(result, sort_keys=True) + "\n", encoding="utf-8")
        return result


class TofuAdapter:
    def __init__(self, service_id: str, backend_config: Path):
        self.service_id = service_id
        self.backend_config = backend_config.resolve()
        if not self.backend_config.is_file():
            raise ReconcileError(f"backend config does not exist: {self.backend_config}")
        self.plan_path: str | None = None
        cache_root = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
        self.environment = os.environ.copy()
        self.environment["TF_DATA_DIR"] = str(
            cache_root / "aws-account-infra" / "tofu" / "supabase" / service_id
        )

    def _base(self) -> list[str]:
        return ["tofu", f"-chdir={TOFU_ROOT}"]

    def plan(self, service: dict, purge: bool) -> None:
        required = ("SUPABASE_ACCESS_TOKEN", "TF_VAR_database_password")
        missing = [name for name in required if not os.environ.get(name)]
        if missing:
            raise ReconcileError(
                "live reconciliation must run beneath asm-exec; missing runtime variables: "
                + ", ".join(missing)
            )
        subprocess.run(
            self._base()
            + [
                "init",
                "-input=false",
                "-reconfigure",
                f"-backend-config={self.backend_config}",
            ],
            cwd=ROOT,
            env=self.environment,
            check=True,
        )
        fd, self.plan_path = tempfile.mkstemp(prefix="supabase-plan-")
        os.close(fd)
        os.chmod(self.plan_path, 0o600)
        command = self._base() + [
            "plan",
            "-input=false",
            f"-out={self.plan_path}",
            f"-var=service_id={self.service_id}",
            f"-var=purge={str(purge).lower()}",
        ]
        try:
            subprocess.run(command, cwd=ROOT, env=self.environment, check=True)
        except Exception:
            os.unlink(self.plan_path)
            self.plan_path = None
            raise

    def apply(self, service: dict, purge: bool) -> dict:
        if not self.plan_path:
            raise ReconcileError("adapter apply called without a saved plan")
        try:
            subprocess.run(
                self._base() + ["apply", "-input=false", "-auto-approve", self.plan_path],
                cwd=ROOT,
                env=self.environment,
                check=True,
            )
            if purge:
                return {"purged": True}
            output = subprocess.run(
                self._base() + ["output", "-json", "project"],
                cwd=ROOT,
                env=self.environment,
                check=True,
                capture_output=True,
                text=True,
            )
            return json.loads(output.stdout)
        finally:
            os.unlink(self.plan_path)
            self.plan_path = None


def committed_catalog_sha(explicit: str | None, live: bool) -> str:
    if explicit:
        if not len(explicit) == 40 or any(char not in "0123456789abcdef" for char in explicit):
            raise ReconcileError("catalog SHA must be a 40-character lowercase Git SHA")
        return explicit
    if live:
        dirty = subprocess.run(
            ["git", "diff", "--quiet", "--", "catalog/catalog.json", "catalog/services"],
            cwd=ROOT,
        )
        if dirty.returncode:
            raise ReconcileError("live reconciliation requires committed catalog inputs")
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()


def reconcile(args: argparse.Namespace) -> dict:
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    if args.service_id not in catalog["services"]:
        raise ReconcileError(f"unknown service {args.service_id!r}")
    service = catalog["services"][args.service_id]
    target = service.get("external_services", {}).get("supabase")
    if not target:
        raise ReconcileError(f"service {args.service_id!r} has no Supabase binding")
    if args.adapter == "tofu":
        gates = json.loads(GATES.read_text(encoding="utf-8"))
        required = ["harvester_credential_rotated", "sensitive_state_ready"]
        if not args.canary:
            required.extend(
                ["template_ready", "adapter_canary_passed", "live_service_vending_enabled"]
            )
        closed = [name for name in required if not gates.get(name)]
        if closed:
            raise ReconcileError("live reconciliation gates are closed: " + ", ".join(closed))
    sha = committed_catalog_sha(args.catalog_sha, args.adapter == "tofu")
    binding_id = f"{service['service']['uid']}#supabase"
    purge = target["lifecycle"] == "purge_requested"
    if target["lifecycle"] == "purged":
        raise ReconcileError("purged is a recorded terminal state, not an executable action")
    if purge and args.confirm_purge != f"{service['service']['uid']}:{sha}":
        raise ReconcileError("purge requires --confirm-purge <service-uid>:<catalog-sha>")

    owner = str(uuid.uuid4())
    journal: Journal
    if args.journal == "file":
        journal = FileJournal(Path(args.journal_file))
    else:
        journal = DynamoDBJournal(args.journal_table, args.aws_region)
    adapter = (
        FakeAdapter(Path(args.fake_state_dir))
        if args.adapter == "fake"
        else TofuAdapter(args.service_id, Path(args.backend_config))
    )

    prior = journal.acquire(binding_id, owner, args.lease_seconds)
    operation_id = (
        prior.get("operation_id")
        if prior.get("desired_commit_sha") == sha
        else str(uuid.uuid4())
    )
    try:
        if (
            not args.force
            and prior.get("stage") == "complete"
            and prior.get("applied_commit_sha") == sha
            and prior.get("lifecycle") == target["lifecycle"]
        ):
            return prior
        common = {
            "operation_id": operation_id,
            "desired_commit_sha": sha,
            "lifecycle": target["lifecycle"],
            "error": None,
        }
        journal.checkpoint(binding_id, owner, {**common, "stage": "validated"})
        if args.fail_after == "validated":
            raise ReconcileError("injected failure after validated")

        if target["lifecycle"] in ("suspended", "archived"):
            result = {"retained": True, "lifecycle": target["lifecycle"]}
        else:
            adapter.plan(service, purge)
            journal.checkpoint(binding_id, owner, {**common, "stage": "planned"})
            if args.fail_after == "planned":
                raise ReconcileError("injected failure after planned")
            result = adapter.apply(service, purge)
            journal.checkpoint(binding_id, owner, {**common, "stage": "applied"})
            if args.fail_after == "applied":
                raise ReconcileError("injected failure after applied")

        recorded = {**common, "stage": "recorded", "result": result}
        journal.checkpoint(binding_id, owner, recorded)
        if args.fail_after == "recorded":
            raise ReconcileError("injected failure after recorded")
        completed = journal.checkpoint(
            binding_id,
            owner,
            {**recorded, "stage": "complete", "applied_commit_sha": sha},
        )
        return completed
    except Exception as exc:
        journal.checkpoint(binding_id, owner, {"error": type(exc).__name__})
        raise
    finally:
        journal.release(binding_id, owner)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("service_id")
    parser.add_argument("--adapter", choices=("fake", "tofu"), default="fake")
    parser.add_argument("--journal", choices=("file", "dynamodb"), default="file")
    parser.add_argument("--journal-file", default="build/external-provider-journal.json")
    parser.add_argument("--journal-table")
    parser.add_argument("--backend-config")
    parser.add_argument("--aws-region", default="us-east-1")
    parser.add_argument("--fake-state-dir", default="build/fake-external-providers")
    parser.add_argument("--catalog-sha")
    parser.add_argument("--confirm-purge")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--lease-seconds", type=int, choices=range(60, 3601), default=3600)
    parser.add_argument("--fail-after", choices=STAGES[:-1])
    args = parser.parse_args()
    if args.journal == "dynamodb" and not args.journal_table:
        parser.error("--journal-table is required with --journal dynamodb")
    if args.adapter == "tofu" and not args.backend_config:
        parser.error("--backend-config is required with --adapter tofu")
    try:
        result = reconcile(args)
    except (ReconcileError, subprocess.CalledProcessError, json.JSONDecodeError) as exc:
        print(f"reconciliation failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
