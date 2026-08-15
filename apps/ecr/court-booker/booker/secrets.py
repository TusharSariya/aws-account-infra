from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

USERNAME_KEY = "my_YMCA_username"
PASSWORD_KEY = "my_YMCA_password"


class CredentialError(RuntimeError):
    """Missing or unreadable My Y credentials."""


@dataclass(frozen=True)
class Credentials:
    username: str
    password: str

    def __repr__(self) -> str:
        return f"Credentials(username={self.username!r}, password='***')"


def _from_mapping(data: dict[str, str]) -> Credentials:
    username = (data.get(USERNAME_KEY) or "").strip()
    password = (data.get(PASSWORD_KEY) or "").strip()
    if not username or not password:
        raise CredentialError(f"need {USERNAME_KEY} and {PASSWORD_KEY}")
    return Credentials(username=username, password=password)


def load_dotenv_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    here = Path(__file__).resolve()
    repo_root = next((p for p in here.parents if (p / "deploy-units.json").exists()), here.parents[1])
    candidates = [
        Path.cwd() / ".env",
        repo_root / ".env",
        here.parents[1] / ".env",
    ]
    for path in candidates:
        if path.is_file():
            load_dotenv(path, override=False)


def load_credentials(*, secret_arn: str | None = None) -> Credentials:
    arn = secret_arn or os.environ.get("SECRET_ARN", "").strip()
    if arn:
        return _from_secrets_manager(arn)
    load_dotenv_files()
    return _from_mapping(os.environ)


def _from_secrets_manager(secret_arn: str) -> Credentials:
    import boto3

    from booker.timing import Stopwatch

    clock = Stopwatch("secretsmanager")
    client_kwargs: dict[str, str] = {}
    endpoint = os.environ.get("AWS_ENDPOINT_URL", "").strip()
    if not endpoint and os.environ.get("LOCALSTACK_HOSTNAME"):
        endpoint = f"http://{os.environ['LOCALSTACK_HOSTNAME']}:4566"
    if endpoint:
        client_kwargs["endpoint_url"] = endpoint
    client = boto3.client("secretsmanager", **client_kwargs)
    clock.mark("client")
    payload = client.get_secret_value(SecretId=secret_arn)["SecretString"]
    clock.mark("get_secret_value")
    data = json.loads(payload)
    if not isinstance(data, dict):
        raise CredentialError("secret JSON must be an object")
    return _from_mapping({str(k): str(v) for k, v in data.items()})
