"""One bounded SSH operation; invoked only by SSHTransport."""
import json
from pathlib import Path
import sys
import time
import paramiko


def execute(config_path, target, command):
    if command not in ("power state", "power on"):
        raise ValueError("Command not allowed")
    cfg = json.loads(Path(config_path).read_text())
    host = cfg["hosts"][target]
    with paramiko.SSHClient() as client:
        client.load_host_keys(str(Path(cfg["known_hosts"]).expanduser()))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        client.connect(host["address"], username=host["username"],
                       key_filename=str(Path(host["key_file"]).expanduser()),
                       allow_agent=False, look_for_keys=False,
                       timeout=5, banner_timeout=5, auth_timeout=5, channel_timeout=5,
                       disabled_algorithms=({"pubkeys": ["rsa-sha2-256", "rsa-sha2-512"]}
                                            if host.get("legacy_rsa_signature", False) else None))
        stdin, stdout, _ = client.exec_command(command, timeout=10)
        stdin.close()
        channel = stdout.channel
        output, errors = bytearray(), bytearray()
        deadline = time.monotonic() + 10
        while True:
            if time.monotonic() > deadline:
                raise TimeoutError("Response deadline")
            if channel.recv_ready():
                output.extend(channel.recv(4096))
            if channel.recv_stderr_ready():
                errors.extend(channel.recv_stderr(4096))
            if len(output) + len(errors) > 16384:
                raise ValueError("Response exceeds limit")
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            time.sleep(0.01)
        code = channel.recv_exit_status()
        if code != 0 or errors:
            raise RuntimeError("Nonzero exit or stderr response")
        return output.decode("utf-8", errors="strict")


if __name__ == "__main__":
    try:
        print(json.dumps({"output": execute(*sys.argv[1:])}))
    except Exception as exc:
        # Never emit keys, passwords, connection objects or full tracebacks.
        print(json.dumps({"error": type(exc).__name__}))
        sys.exit(1)
