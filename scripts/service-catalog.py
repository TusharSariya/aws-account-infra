#!/usr/bin/env python3
"""Validate service manifests and render deterministic vending input.

JSON Schema is the sole shape authority. This module only enforces constraints that
span records, depend on capacity, or compare with an earlier catalog revision.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[1]
SERVICES = ROOT / "catalog" / "services"
CLUSTERS = ROOT / "catalog" / "kubernetes" / "clusters"
GENERATED = ROOT / "catalog" / "catalog.json"
SERVICE_SCHEMA_PATH = ROOT / "catalog" / "schema" / "service.schema.json"
CLUSTER_SCHEMA_PATH = ROOT / "catalog" / "schema" / "cluster.schema.json"

ACCOUNT_ID = re.compile(r"^[0-9]{12}$")
QUANTITY = re.compile(r"^(?P<number>[0-9]+)(?P<unit>m|Mi|Gi)$")
LIFECYCLE_TRANSITIONS = {
    "active": {"active", "suspended"},
    "suspended": {"suspended", "archived"},
    "archived": {"archived"},
}
CAPACITY_FIELDS = (
    "requests_cpu",
    "requests_memory",
    "limits_memory",
    "requests_ephemeral_storage",
    "limits_ephemeral_storage",
    "pods",
    "physical_storage",
)


class CatalogError(ValueError):
    pass


def fail(path: Path, message: str) -> None:
    try:
        display_path = path.relative_to(ROOT)
    except ValueError:
        display_path = path
    raise CatalogError(f"{display_path}: {message}")


def _load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _schema_validator(path: Path) -> Draft202012Validator:
    schema = json.loads(path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema, format_checker=FormatChecker())


def _validate_schema(path: Path, raw: object, schema_path: Path) -> dict:
    errors = sorted(
        _schema_validator(schema_path).iter_errors(raw),
        key=lambda error: tuple(str(part) for part in error.absolute_path),
    )
    if errors:
        error = errors[0]
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        fail(path, f"{location}: {error.message}")
    assert isinstance(raw, dict)
    return raw


def load_manifest(path: Path) -> dict:
    return _validate_schema(path, _load_yaml(path), SERVICE_SCHEMA_PATH)


def load_cluster(path: Path) -> dict:
    return _validate_schema(path, _load_yaml(path), CLUSTER_SCHEMA_PATH)


def _quantity_value(value: str | int) -> int:
    if isinstance(value, int):
        return value
    match = QUANTITY.fullmatch(value)
    if not match:
        raise CatalogError(f"unsupported capacity quantity {value!r}")
    number = int(match.group("number"))
    unit = match.group("unit")
    return number * 1024 if unit == "Gi" else number


def _validate_capacity(services: dict[str, dict], clusters: dict[str, dict]) -> None:
    totals = {
        cluster_id: {field: 0 for field in CAPACITY_FIELDS}
        for cluster_id in clusters
    }
    for service_id, service in services.items():
        for cluster_id, target in service["kubernetes"].items():
            if cluster_id not in clusters:
                raise CatalogError(f"service {service_id!r} targets unknown cluster {cluster_id!r}")
            profile_name = target["quota_profile"]
            profiles = clusters[cluster_id]["quota_profiles"]
            if profile_name not in profiles:
                raise CatalogError(
                    f"service {service_id!r} uses unknown quota profile "
                    f"{cluster_id}/{profile_name}"
                )
            # Static validation charges every activated namespace. Only a successful
            # live reconciliation may record capacity_released for an inactive tenant.
            profile = profiles[profile_name]
            for field in CAPACITY_FIELDS:
                totals[cluster_id][field] += _quantity_value(profile[field])

    for cluster_id, allocated in totals.items():
        budget = clusters[cluster_id]["capacity"]
        for field, used in allocated.items():
            available = _quantity_value(budget[field])
            if used > available:
                raise CatalogError(
                    f"cluster {cluster_id!r} exceeds {field} capacity: "
                    f"allocated {used}, budget {available}"
                )


def _claim_unique(claims: dict[str, str], value: str, owner: str, field: str) -> None:
    normalized = value.casefold()
    if normalized in claims:
        raise CatalogError(f"{field} {value!r} for {owner} duplicates {claims[normalized]}")
    claims[normalized] = owner


def build_catalog() -> dict:
    clusters: dict[str, dict] = {}
    for path in sorted(CLUSTERS.glob("*.yaml")):
        cluster = load_cluster(path)
        cluster_id = cluster["cluster"]
        if cluster_id in clusters:
            fail(path, f"duplicate cluster {cluster_id!r}")
        if path.stem != cluster_id:
            fail(path, f"file name must match cluster {cluster_id!r}")
        clusters[cluster_id] = cluster

    services: dict[str, dict] = {}
    claims: dict[str, dict[str, str]] = {
        field: {}
        for field in ("uid", "repository identity", "account email", "account name", "namespace", "ECR repository", "hostname")
    }
    for path in sorted(SERVICES.glob("*.yaml")):
        manifest = load_manifest(path)
        service_id = manifest["service"]["id"]
        if service_id in services:
            fail(path, f"duplicate service.id {service_id!r}")
        if path.stem != service_id:
            fail(path, f"file name must match service.id {service_id!r}")
        if manifest["repository"]["identity"].split("/", 1)[1] != manifest["repository"]["name"]:
            fail(path, "repository.identity name must equal repository.name")

        _claim_unique(claims["uid"], manifest["service"]["uid"], service_id, "catalog UID")
        _claim_unique(
            claims["repository identity"],
            manifest["repository"]["identity"],
            service_id,
            "repository identity",
        )
        for environment, account in manifest["accounts"].items():
            owner = f"{service_id}/{environment}"
            _claim_unique(claims["account email"], account["root_email"], owner, "root_email")
            _claim_unique(claims["account name"], account["name"], owner, "account name")
        for cluster_id, target in manifest["kubernetes"].items():
            owner = f"{service_id}/{cluster_id}"
            namespace = f"{service_id}-local"
            _claim_unique(claims["namespace"], namespace, owner, "namespace")
            _claim_unique(claims["ECR repository"], target["ecr_repository"], owner, "ECR repository")
            _claim_unique(claims["hostname"], target["ingress_hostname"], owner, "hostname")
            secret_names: set[str] = set()
            for secret in target["secrets"]:
                if secret["name"] in secret_names:
                    fail(path, f"duplicate secret contract {owner}/{secret['name']}")
                secret_names.add(secret["name"])
        services[service_id] = manifest

    _validate_capacity(services, clusters)
    return {"version": 1, "kubernetes_clusters": clusters, "services": services}


def check_immutable(previous: dict, current: dict, allow_lifecycle_reversal: bool = False) -> None:
    previous_services = previous.get("services", {})
    current_services = current.get("services", {})
    for service_id, old_service in previous_services.items():
        if service_id not in current_services:
            raise CatalogError(f"service {service_id!r} cannot be deleted; archive its targets")
        new_service = current_services[service_id]
        new_accounts = new_service["accounts"]
        for environment, old_account in old_service["accounts"].items():
            if environment not in new_accounts:
                raise CatalogError(f"account key {service_id}/{environment} cannot be deleted")
            new_account = new_accounts[environment]
            if old_account.get("account_id") and new_account.get("account_id") != old_account["account_id"]:
                raise CatalogError(f"account_id for {service_id}/{environment} is immutable")
            for field in ("name", "root_email"):
                if old_account.get("account_id") and new_account[field] != old_account[field]:
                    raise CatalogError(f"{field} for provisioned account {service_id}/{environment} is immutable")

        for cluster_id, old_target in old_service.get("kubernetes", {}).items():
            if cluster_id not in new_service.get("kubernetes", {}):
                raise CatalogError(f"Kubernetes target {service_id}/{cluster_id} cannot be deleted; archive it")
            new_target = new_service["kubernetes"][cluster_id]
            old_lifecycle = old_target["lifecycle"]
            new_lifecycle = new_target["lifecycle"]
            if (
                not allow_lifecycle_reversal
                and new_lifecycle not in LIFECYCLE_TRANSITIONS[old_lifecycle]
            ):
                raise CatalogError(
                    f"lifecycle transition {service_id}/{cluster_id} "
                    f"{old_lifecycle} -> {new_lifecycle} requires operator override"
                )
            immutable = {
                "catalog UID": (old_service["service"].get("uid"), new_service["service"].get("uid")),
                "repository identity": (old_service["repository"].get("identity"), new_service["repository"].get("identity")),
                "namespace": (f"{service_id}-local", f"{new_service['service']['id']}-local"),
                "ECR repository": (old_target["ecr_repository"], new_target["ecr_repository"]),
                "hostname": (old_target["ingress_hostname"], new_target["ingress_hostname"]),
            }
            for field, (old_value, new_value) in immutable.items():
                if old_value != new_value:
                    raise CatalogError(f"{field} for activated target {service_id}/{cluster_id} is immutable")


def _load_previous_ref(previous_ref: str) -> dict:
    try:
        payload = subprocess.check_output(
            ["git", "show", f"{previous_ref}:catalog/catalog.json"], cwd=ROOT, text=True
        )
    except subprocess.CalledProcessError as exc:
        raise CatalogError(f"could not read catalog/catalog.json from {previous_ref}") from exc
    return json.loads(payload)


def render(
    check: bool,
    previous_ref: str | None = None,
    allow_lifecycle_reversal: bool = False,
) -> int:
    current = build_catalog()
    if previous_ref:
        check_immutable(
            _load_previous_ref(previous_ref),
            current,
            allow_lifecycle_reversal=allow_lifecycle_reversal,
        )
    if GENERATED.exists():
        check_immutable(
            json.loads(GENERATED.read_text(encoding="utf-8")),
            current,
            allow_lifecycle_reversal=allow_lifecycle_reversal,
        )
    payload = json.dumps(current, indent=2, sort_keys=True) + "\n"
    if check:
        if not GENERATED.exists() or GENERATED.read_text(encoding="utf-8") != payload:
            print("catalog/catalog.json is stale; run scripts/service-catalog.py render", file=sys.stderr)
            return 1
    else:
        GENERATED.write_text(payload, encoding="utf-8")
    return 0


def record_account(service_id: str, environment: str, account_id: str) -> int:
    if not ACCOUNT_ID.fullmatch(account_id):
        raise CatalogError("account_id must contain exactly 12 digits")
    matches = []
    for path in sorted(SERVICES.glob("*.yaml")):
        manifest = load_manifest(path)
        if manifest["service"]["id"] == service_id:
            matches.append((path, manifest))
    if len(matches) != 1:
        raise CatalogError(f"expected exactly one manifest for service {service_id!r}")
    path, manifest = matches[0]
    if environment not in manifest["accounts"]:
        raise CatalogError(f"unknown account key {service_id}/{environment}")
    current = manifest["accounts"][environment]["account_id"]
    if current and current != account_id:
        raise CatalogError(f"account_id for {service_id}/{environment} is already {current}")
    manifest["accounts"][environment]["account_id"] = account_id
    path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return render(check=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("--previous-ref")
    validate.add_argument("--allow-lifecycle-reversal", action="store_true")
    subparsers.add_parser("render")
    record = subparsers.add_parser("record-account")
    record.add_argument("service_id")
    record.add_argument("environment")
    record.add_argument("account_id")
    args = parser.parse_args()
    try:
        if args.command == "record-account":
            return record_account(args.service_id, args.environment, args.account_id)
        return render(
            check=args.command == "validate",
            previous_ref=getattr(args, "previous_ref", None),
            allow_lifecycle_reversal=getattr(args, "allow_lifecycle_reversal", False),
        )
    except (CatalogError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
