#!/usr/bin/env python3
"""Bounded local CPU/CUDA acceptance using cached images; removes test containers."""

import argparse
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
import uuid

CTR = ["ctr", "--namespace", "k8s.io"]


def request(port, path, payload=None):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(payload).encode() if payload else None,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def smoke(versions, kind):
    name = "worker-acceptance-" + uuid.uuid4().hex
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    command = CTR + [
        "run",
        "--rm",
        "--net-host",
        "--cpus",
        "4",
        "--memory-limit",
        str(4 * 1024**3),
        "--mount",
        "type=bind,src=/var/lib/homelab-inference/models,dst=/models,options=rbind:ro",
    ]
    if kind == "cuda":
        command += [
            "--runc-binary",
            "/usr/bin/nvidia-container-runtime",
            "--env",
            "NVIDIA_VISIBLE_DEVICES=all",
            "--env",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
        ]
    else:
        command += ["--env", "NVIDIA_VISIBLE_DEVICES=void"]
    command += [
        versions["images"][kind],
        name,
        "/app/llama-server",
        "--model",
        "/models/" + versions["model"]["file"],
        "--alias",
        name,
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--parallel",
        "1",
        "--ctx-size",
        "4096",
        "--n-gpu-layers",
        "99" if kind == "cuda" else "0",
    ]
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT)
        try:
            deadline = time.monotonic() + 120
            while True:
                if process.poll() is not None:
                    raise RuntimeError("Runtime exited before becoming healthy")
                try:
                    if request(port, "/health").get("status") == "ok":
                        break
                except (OSError, urllib.error.HTTPError):
                    pass
                if time.monotonic() >= deadline:
                    raise TimeoutError("Runtime startup exceeded 120 seconds")
                time.sleep(1)
            if kind == "cuda":
                tasks = subprocess.check_output(CTR + ["tasks", "list"], text=True)
                pid = next(
                    line.split()[1]
                    for line in tasks.splitlines()
                    if line.split() and line.split()[0] == name
                )
                usage = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-compute-apps=pid,used_gpu_memory",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                )
                assert any(
                    row.split(",")[0].strip() == pid
                    and int(row.split(",")[1].strip()) > 0
                    for row in usage.splitlines()
                ), "Runtime has no GPU memory allocation"
            result = request(
                port,
                "/v1/chat/completions",
                {
                    "model": name,
                    "messages": [
                        {"role": "user", "content": "Reply with just the word ready."}
                    ],
                    "max_tokens": 32,
                    "temperature": 0,
                    "chat_template_kwargs": {"enable_thinking": False},
                },
            )
            assert result["model"] == name, "Unexpected server answered"
            assert result["choices"][0]["message"]["content"].strip(), (
                "Empty completion"
            )
            print(
                json.dumps(
                    {
                        "backend": kind,
                        "model": versions["model"]["name"],
                        "completion": result["choices"][0],
                        "usage": result["usage"],
                    }
                ),
                flush=True,
            )
        except Exception:
            log.seek(0, 2)
            log.seek(max(0, log.tell() - 6000))
            print(log.read().decode(errors="replace"), flush=True)
            raise
        finally:
            subprocess.run(
                CTR + ["tasks", "kill", "--signal", "SIGKILL", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            # Remove only this UUID-named validation task/container if --rm did not.
            subprocess.run(
                CTR + ["tasks", "delete", "--force", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            subprocess.run(
                CTR + ["containers", "delete", name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
            )
            remaining = subprocess.check_output(
                CTR + ["containers", "list", "--quiet"], text=True
            )
            assert name not in remaining.splitlines(), (
                "Validation container cleanup failed"
            )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--versions", required=True)
    args = parser.parse_args()
    versions = json.loads(Path(args.versions).read_text())
    model = Path("/var/lib/homelab-inference/models") / versions["model"]["file"]
    with model.open("rb") as source:
        assert (
            hashlib.file_digest(source, "sha256").hexdigest()
            == versions["model"]["sha256"]
        )
    for kind in ("cpu", "cuda"):
        smoke(versions, kind)


if __name__ == "__main__":
    main()
