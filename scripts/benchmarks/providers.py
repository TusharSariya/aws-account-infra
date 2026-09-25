import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import time

parser = argparse.ArgumentParser(
    description="Compare upstream OpenTofu init with local provider archive restoration; no Nexus transport."
)
parser.add_argument(
    "--repo", type=pathlib.Path, default=pathlib.Path(__file__).resolve().parents[2]
)
parser.add_argument(
    "--tofu",
    type=pathlib.Path,
    required=True,
    help="Path to real OpenTofu binary, not a version-manager shim",
)
parser.add_argument("--output", type=pathlib.Path, required=True)
args = parser.parse_args()
repo = args.repo.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(repo / "scripts"))
from dependency_cache import pack, unpack

rows = []
with tempfile.TemporaryDirectory(prefix="provider-benchmark-") as tmp:
    root = pathlib.Path(tmp)
    archive = root / "providers.zip"
    home = root / "home"
    home.mkdir()
    for repeat in range(3):
        for variant in ["before-cold", "after-restored"]:
            job = root / f"{variant}-{repeat}"
            job.mkdir()
            for source in (repo / "live/proxmox/homelab").glob("*.tf"):
                shutil.copy(source, job / source.name)
            shutil.copy(
                repo / "live/proxmox/homelab/.terraform.lock.hcl",
                job / ".terraform.lock.hcl",
            )
            config = root / "tofurc"
            config.write_text("")
            env = {
                "PATH": os.environ["PATH"],
                "HOME": str(home),
                "TF_CLI_CONFIG_FILE": str(config),
                "CHECKPOINT_DISABLE": "1",
            }
            start = time.perf_counter()
            restore = 0
            if variant == "after-restored":
                cache = job / "plugin-cache"
                cache.mkdir()
                unpack(archive, cache)
                restore = time.perf_counter() - start
                env["TF_PLUGIN_CACHE_DIR"] = str(cache)
            initstart = time.perf_counter()
            with (out / f"provider-{variant}-{repeat}.log").open("w") as f:
                result = subprocess.run(
                    [
                        str(args.tofu.resolve()),
                        "init",
                        "-backend=false",
                        "-input=false",
                        "-lockfile=readonly",
                    ],
                    cwd=job,
                    env=env,
                    stdout=f,
                    stderr=subprocess.STDOUT,
                    check=False,
                )
            end = time.perf_counter()
            row = {
                "variant": variant,
                "repeat": repeat,
                "total_seconds": end - start,
                "restore_seconds": restore,
                "init_seconds": end - initstart,
                "returncode": result.returncode,
            }
            rows.append(row)
            if result.returncode:
                raise SystemExit(result.returncode)
            if variant == "before-cold" and repeat == 0:
                start = time.perf_counter()
                pack(job / ".terraform/providers", archive)
                export = time.perf_counter() - start
                size = archive.stat().st_size
                expanded = sum(
                    p.stat().st_size
                    for p in (job / ".terraform/providers").rglob("*")
                    if p.is_file()
                )
            (out / "providers.json").write_text(
                json.dumps(
                    {
                        "provider": "bpg/proxmox from committed lockfile",
                        "platform": "darwin_arm64",
                        "transport": "local archive; Nexus HTTP latency excluded",
                        "export_seconds": export,
                        "archive_bytes": size,
                        "expanded_bytes": expanded,
                        "runs": rows,
                    },
                    indent=2,
                )
                + "\n"
            )
            print(variant, repeat, round(row["total_seconds"], 3), flush=True)
