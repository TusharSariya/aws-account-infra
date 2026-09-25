import argparse
import json
import os
import pathlib
import platform
import shutil
import subprocess
import tempfile
import time

parser = argparse.ArgumentParser(
    description="Compare identical ARM application tests with cold and warm dependency directories."
)
parser.add_argument("--before", type=pathlib.Path, required=True)
parser.add_argument("--after", type=pathlib.Path, required=True)
parser.add_argument("--output", type=pathlib.Path, required=True)
args = parser.parse_args()
base = args.before.resolve()
after = args.after.resolve()
out = args.output.resolve()
out.mkdir(parents=True, exist_ok=True)
before_revision = subprocess.check_output(
    ["git", "rev-parse", "HEAD"], cwd=base, text=True
).strip()
assert (
    subprocess.check_output(
        [
            "git",
            "diff",
            before_revision,
            "HEAD",
            "--",
            "apps/lambda/python/3.14/court-booker",
        ],
        cwd=after,
    )
    == b""
), "Application source must match"
real = shutil.which("docker")
rows = []
with tempfile.TemporaryDirectory(prefix="ci-benchmark-") as scratch:
    root = pathlib.Path(scratch)
    bin = root / "bin"
    bin.mkdir()
    wrapper = bin / "docker"
    wrapper.write_text("""#!/usr/bin/env python3
import os,subprocess,sys,time,json
args=sys.argv[1:];operation=' '.join(args[:2]);start=time.perf_counter()
if args[0]=='run':args[1:1]=['-e','UV_PROJECT_ENVIRONMENT=/bench/venv','-e','UV_CACHE_DIR=/bench/uv','--mount','type=bind,src='+os.environ['BENCH_CACHE']+',dst=/bench']
result=subprocess.run([os.environ['BENCH_DOCKER'],*args])
with open(os.environ['BENCH_TRACE'],'a') as f:f.write(json.dumps({'operation':operation,'seconds':time.perf_counter()-start,'returncode':result.returncode})+'\\n')
sys.exit(result.returncode)
""")
    wrapper.chmod(0o755)
    for cohort in ["cold-dependencies", "warm-dependencies"]:
        caches = {}
        for name in ["before", "after"]:
            caches[name] = root / (cohort + "-" + name)
            caches[name].mkdir()
        for repeat in range(6):
            for name, path in (
                [("before", base), ("after", after)]
                if repeat % 2 == 0
                else [("after", after), ("before", base)]
            ):
                cache = caches[name]
                if cohort == "cold-dependencies":
                    cache = cache / str(repeat)
                    cache.mkdir()
                trace = out / f"{cohort}-{name}-{repeat}-docker.jsonl"
                log = out / f"{cohort}-{name}-{repeat}.log"
                trace.write_text("")
                env = {
                    k: v
                    for k, v in os.environ.items()
                    if not k.startswith(("AWS_", "HOMELAB_", "LAMBDA_"))
                }
                env.update(
                    PATH=str(bin) + ":" + env["PATH"],
                    BENCH_CACHE=str(cache),
                    BENCH_DOCKER=real,
                    BENCH_TRACE=str(trace),
                )
                start = time.perf_counter()
                with log.open("w") as f:
                    result = subprocess.run(
                        ["bash", "scripts/lambda-package-arm.sh", "test"],
                        cwd=path,
                        env=env,
                        stdout=f,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                row = {
                    "variant": name,
                    "cohort": cohort,
                    "repeat": repeat,
                    "seconds": time.perf_counter() - start,
                    "returncode": result.returncode,
                    "trace": [json.loads(x) for x in trace.read_text().splitlines()],
                    "log": log.name,
                    "warmup": cohort == "warm-dependencies" and repeat == 0,
                }
                rows.append(row)
                (out / "arm.json").write_text(
                    json.dumps(
                        {
                            "host": platform.platform(),
                            "platform": "linux/arm64 on native ARM Docker; not CI x64 emulation",
                            "before": subprocess.check_output(
                                ["git", "rev-parse", "HEAD"], cwd=base, text=True
                            ).strip(),
                            "after": subprocess.check_output(
                                ["git", "rev-parse", "HEAD"], cwd=after, text=True
                            ).strip(),
                            "image_cache": "warm BuildKit layers and loaded images; only dependency/venv cache is cold",
                            "runs": rows,
                        },
                        indent=2,
                    )
                    + "\n"
                )
                print(
                    name,
                    cohort,
                    repeat,
                    round(row["seconds"], 3),
                    result.returncode,
                    flush=True,
                )
                if result.returncode:
                    raise SystemExit(result.returncode)
