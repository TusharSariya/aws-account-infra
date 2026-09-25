"""Bounded Nexus archives for public dependency caches, never workspace/state files."""

import argparse
import base64
import hashlib
import io
import json
import os
import platform
import shutil
import tempfile
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

FORMAT = 1
LIMIT = 2 * 1024**3
ARCHIVE_LIMIT = 512 * 1024**2
KINDS = {"providers", "tflint", "go", "python"}
BASE = "http://nexus.homelab-cache.svc.cluster.local:8081/repository/raw-dependencies/"


class IntegrityError(ValueError):
    pass


class ExportTooLarge(ValueError):
    pass


def key(kind, toolchain, dependency_hash, branch, system=None, machine=None, scope=""):

    if kind not in KINDS or not toolchain or not dependency_hash:
        raise ValueError("Explicit cache kind, toolchain and dependency hash required")
    # Every entry is branch isolated. Main can be imported deliberately later;
    # PR writers must never populate a stable branch's executable caches.
    identity = [
        FORMAT,
        kind,
        system or platform.system(),
        machine or platform.machine(),
        toolchain,
        dependency_hash,
        branch,
        scope,
    ]
    return hashlib.sha256(json.dumps(identity).encode()).hexdigest()


def pack(directory, output=None):
    files, manifest = {}, {}
    total = 0
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            if not path.resolve().is_relative_to(directory.resolve()):
                raise IntegrityError("Dependency cache link escapes its directory")
            name = path.relative_to(directory).as_posix()
            manifest[name] = {
                "link": os.path.relpath(path.resolve(), path.parent.resolve())
            }
            continue
        if not path.is_file():
            continue
        name = path.relative_to(directory).as_posix()
        if any(
            part in {".terraform", ".git", ".aws", ".ssh"}
            for part in path.relative_to(directory).parts
        ) or any(
            word == path.name.lower()
            for word in ("terraform.tfstate", "tfplan", "credentials", ".netrc")
        ):
            raise IntegrityError("Private or state content in dependency cache")
        total += path.stat().st_size
        if total > LIMIT:
            raise ExportTooLarge("Cache exceeds archive limit")
        with path.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        files[name] = path
        manifest[name] = {
            "sha256": digest,
            "mode": path.stat().st_mode & 0o777,
        }
    memory = output is None
    output = io.BytesIO() if memory else output
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=1) as archive:
        archive.writestr(
            "manifest.json", json.dumps({"format": FORMAT, "files": manifest})
        )
        for name, data in files.items():
            archive.write(data, "data/" + name)
    return output.getvalue() if memory else output


def unpack(body, directory):
    try:
        with zipfile.ZipFile(
            io.BytesIO(body) if isinstance(body, bytes) else body
        ) as archive:
            names = archive.namelist()
            if (
                len(names) != len(set(names))
                or sum(i.file_size for i in archive.infolist()) > LIMIT
            ):
                raise IntegrityError("Duplicate entries or oversized cache")
            if archive.getinfo("manifest.json").file_size > 8 * 1024**2:
                raise IntegrityError("Oversized archive manifest")
            manifest = json.loads(archive.read("manifest.json"))
            if manifest["format"] != FORMAT or set(names) != {
                "manifest.json",
                *("data/" + n for n, m in manifest["files"].items() if "link" not in m),
            }:
                raise IntegrityError("Unexpected cache format or members")
            links = {n for n, m in manifest["files"].items() if "link" in m}
            if any(
                any(parent.as_posix() in links for parent in PurePosixPath(n).parents)
                for n in manifest["files"]
            ):
                raise IntegrityError("Archive writes through a symlink")
            with tempfile.TemporaryDirectory(dir=directory.parent) as temp:
                staging = Path(temp).resolve()
                for name, metadata in manifest["files"].items():
                    path = PurePosixPath(name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not name
                        or "\\" in name
                    ):
                        raise IntegrityError("Unsafe archive member")
                    if "link" in metadata:
                        destination = staging / name
                        target = metadata["link"]
                        if Path(target).is_absolute() or not (
                            destination.parent / target
                        ).resolve().is_relative_to(staging):
                            raise IntegrityError("Unsafe archive link")
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        destination.symlink_to(target)
                        continue
                    if not (staging / name).resolve().is_relative_to(staging):
                        raise IntegrityError("Archive member escapes through a link")
                    destination = staging / name
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    digest = hashlib.sha256()
                    with (
                        archive.open("data/" + name) as source,
                        destination.open("wb") as target,
                    ):
                        while chunk := source.read(1024 * 1024):
                            digest.update(chunk)
                            target.write(chunk)
                    if digest.hexdigest() != metadata["sha256"]:
                        raise IntegrityError("Dependency checksum mismatch")
                    destination.chmod(metadata["mode"] & 0o755)
                if directory.exists():
                    shutil.rmtree(directory)
                os.replace(staging, directory)
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise IntegrityError("Invalid dependency archive") from exc


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def transfer(mode, identity, directory, password="", opener=None):
    start = time.monotonic()
    result, size = "miss", 0
    opener = opener or urllib.request.build_opener(NoRedirect())
    try:
        if mode == "restore":
            with tempfile.TemporaryFile(dir=directory.parent) as body:
                with opener.open(BASE + identity + ".zip", timeout=15) as response:
                    while chunk := response.read(1024 * 1024):
                        size += len(chunk)
                        if size > ARCHIVE_LIMIT:
                            raise IntegrityError("Archive response exceeds limit")
                        body.write(chunk)
                body.seek(0)
                unpack(body, directory)
            result = "hit"
        elif mode == "save":
            if not password:
                result = "no-writer"
            else:
                with tempfile.TemporaryFile(dir=directory.parent) as body:
                    pack(directory, body)
                    size = body.tell()
                    if size > ARCHIVE_LIMIT:
                        raise ExportTooLarge("Compressed archive exceeds limit")
                    body.seek(0)
                    auth = base64.b64encode(
                        ("cache-build-writer:" + password).encode()
                    ).decode()
                    request = urllib.request.Request(
                        BASE + identity + ".zip",
                        data=body,
                        method="PUT",
                        headers={
                            "Authorization": "Basic " + auth,
                            "Content-Type": "application/zip",
                            "Content-Length": str(size),
                        },
                    )
                    with opener.open(request, timeout=30):
                        pass
                result = "saved"
        else:
            raise ValueError("Unknown cache operation")
    except ExportTooLarge:
        result = "export-too-large"
    except urllib.error.HTTPError as error:
        result = "miss" if mode == "restore" and error.code == 404 else "unavailable"
        error.close()
    except OSError:
        result = "unavailable"  # Misses/denied exports rebuild; integrity failures propagate.
    receipt = {
        "cache": identity,
        "operation": mode,
        "result": result,
        "seconds": round(time.monotonic() - start, 3),
        "bytes": size,
    }
    print(json.dumps(receipt))
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["restore", "save"])
    parser.add_argument("kind", choices=sorted(KINDS))
    parser.add_argument("--toolchain", required=True)
    parser.add_argument("--dependencies", required=True)
    args = parser.parse_args()
    directory = Path(os.environ["RUNNER_TEMP"]) / "homelab-dependencies" / args.kind
    directory.mkdir(parents=True, exist_ok=True)
    identity = key(
        args.kind,
        args.toolchain,
        args.dependencies,
        os.environ["CACHE_BRANCH"],
        scope=os.environ.get("CACHE_SCOPE", ""),
    )
    transfer(args.mode, identity, directory, os.environ.get("CACHE_PASSWORD", ""))
    if args.mode == "restore":
        variables = {
            "providers": ["TF_PLUGIN_CACHE_DIR"],
            "tflint": ["TFLINT_PLUGIN_DIR"],
            "go": ["GOCACHE"],
            "python": ["UV_CACHE_DIR", "PIP_CACHE_DIR"],
        }[args.kind]
        with open(os.environ["GITHUB_ENV"], "a") as output:
            output.writelines(
                variable + "=" + str(directory) + "\n" for variable in variables
            )


if __name__ == "__main__":
    main()
