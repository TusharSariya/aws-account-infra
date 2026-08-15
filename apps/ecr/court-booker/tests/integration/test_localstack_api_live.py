from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import pytest

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv(*_args, **_kwargs):
        return False

from booker.secrets import PASSWORD_KEY, USERNAME_KEY

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ROOT = Path(__file__).resolve().parents[2]
REPO = ROOT.parents[2]
TZ = ZoneInfo("America/St_Johns")


def _client(service: str):
    return boto3.client(
        service,
        endpoint_url=ENDPOINT,
        region_name=REGION,
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )


def _localstack_up() -> bool:
    try:
        _client("sts").get_caller_identity()
        return True
    except Exception:
        return False


def _live_requested() -> bool:
    return os.environ.get("COURT_BOOKER_LIVE", "").strip() in {"1", "true", "yes"}


pytestmark = pytest.mark.skipif(
    (not _live_requested()) or (not _localstack_up()),
    reason="Set COURT_BOOKER_LIVE=1 and start LocalStack to hit Upace from a zip Lambda",
)


def _creds() -> dict[str, str]:
    load_dotenv(REPO / ".env", override=False)
    username = os.environ.get(USERNAME_KEY, "").strip()
    password = os.environ.get(PASSWORD_KEY, "").strip()
    if not username or not password:
        pytest.skip("repo-root .env is missing My Y credentials")
    return {USERNAME_KEY: username, PASSWORD_KEY: password}


def _package_api_zip(work: Path) -> Path:
    staging = work / "pkg"
    staging.mkdir()
    shutil.copytree(
        ROOT / "booker",
        staging / "booker",
        ignore=shutil.ignore_patterns("__pycache__", "upace.py"),
    )
    shutil.copy(ROOT / "bookings.yaml", staging / "bookings.yaml")
    generated = REPO / "generated" / "upace" / "python"
    if not (generated / "upace").is_dir():
        pytest.skip("generated/upace/python is missing; run scripts/sdk-generate.sh upace python")
    shutil.copytree(generated / "upace", staging / "upace", ignore=shutil.ignore_patterns("__pycache__"))
    machine = platform.machine().lower()
    docker_platform = "linux/arm64" if machine in {"arm64", "aarch64"} else "linux/amd64"
    subprocess.check_call(
        [
            "docker",
            "run",
            "--rm",
            "--platform",
            docker_platform,
            "--entrypoint",
            "pip",
            "-v",
            f"{staging}:/var/task",
            "public.ecr.aws/lambda/python:3.12",
            "install",
            "--no-cache-dir",
            "-q",
            "-t",
            "/var/task",
            "pyyaml==6.0.2",
            "pydantic>=2.11",
            "urllib3>=2.6.3,<3",
            "python-dateutil>=2.8.2",
            "typing-extensions>=4.7.1",
        ],
    )
    dest = work / "booker-api.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in staging.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and ".dist-info" not in path.parts:
                archive.write(path, path.relative_to(staging).as_posix())
    return dest


def _lambda_env(parameter_name: str) -> dict[str, str]:
    return {
        "BOOKER_BROWSER": "api",
        "CREDENTIALS_PARAMETER": parameter_name,
        "BOOKINGS_PATH": "bookings.yaml",
        "TZ": "America/St_Johns",
    }


@pytest.fixture(scope="module")
def api_stack(tmp_path_factory):
    work = tmp_path_factory.mktemp("booker-api-zip")
    zip_path = _package_api_zip(work)
    suffix = uuid.uuid4().hex[:8]
    parameter_name = f"/staging/court-booker-api/my-y-live-{suffix}"
    function_name = f"court-booker-api-{suffix}"
    role_arn = "arn:aws:iam::000000000000:role/court-booker-lambda"
    ssm = _client("ssm")
    lam = _client("lambda")
    ssm.put_parameter(
        Name=parameter_name,
        Value=json.dumps(_creds()),
        Type="SecureString",
        Overwrite=True,
    )
    with zip_path.open("rb") as handle:
        lam.create_function(
            FunctionName=function_name,
            Runtime="python3.12",
            Role=role_arn,
            Handler="booker.handler.lambda_handler",
            Code={"ZipFile": handle.read()},
            Timeout=60,
            MemorySize=256,
            Architectures=["arm64"] if platform.machine().lower() in {"arm64", "aarch64"} else ["x86_64"],
            Environment={"Variables": _lambda_env(parameter_name)},
        )
    try:
        lam.get_waiter("function_active").wait(FunctionName=function_name)
    except Exception:
        time.sleep(3)
    yield {"function_name": function_name, "parameter_name": parameter_name, "suffix": suffix}
    try:
        lam.delete_function(FunctionName=function_name)
    except Exception:
        pass
    try:
        ssm.delete_parameter(Name=parameter_name)
    except Exception:
        pass


def _invoke(function_name: str, payload: dict, *, allow_error: bool = False) -> dict:
    lam = _client("lambda")
    response = lam.invoke(
        FunctionName=function_name,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload).encode("utf-8"),
    )
    raw = response["Payload"].read().decode("utf-8")
    body = json.loads(raw)
    if allow_error:
        assert response.get("FunctionError") == "Unhandled", body
        error_message = body.get("errorMessage") or raw
        try:
            return json.loads(error_message)
        except json.JSONDecodeError:
            pytest.fail(f"failure did not raise BookingFailed JSON: {body}")
    assert "FunctionError" not in response, body
    return body


def _find_open_slot(target: date) -> str | None:
    generated = REPO / "generated" / "upace" / "python"
    sys.path.insert(0, str(generated))
    from booker.http import UpaceHttpBooker
    from booker.results import DRY_RUN
    from booker.secrets import Credentials
    from booker.stub import BookingRequest

    mapping = _creds()
    creds = Credentials(username=mapping[USERNAME_KEY], password=mapping[PASSWORD_KEY])
    client = UpaceHttpBooker()
    for hour in range(6, 19):
        hhmm = f"{hour:02d}:00"
        result = client.book(
            BookingRequest(
                activity_key="court2",
                activity_label="Court 2",
                target_date=target,
                hhmm=hhmm,
                duration_min=60,
                people=1,
                dry_run=True,
                equipment_id=12739,
            ),
            creds,
        )
        if result.status == DRY_RUN:
            return hhmm
    return None


def test_bad_password_fails_the_lambda(api_stack):
    lam = _client("lambda")
    ssm = _client("ssm")
    ssm.put_parameter(
        Name=api_stack["parameter_name"],
        Value=json.dumps({USERNAME_KEY: "nobody@example.com", PASSWORD_KEY: "wrong"}),
        Type="SecureString",
        Overwrite=True,
    )
    time.sleep(1)
    try:
        body = _invoke(
            api_stack["function_name"],
            {"source": "adhoc", "activity": "court2", "date": "2026-08-17", "time": "06:00"},
            allow_error=True,
        )
        assert body["status"] == "auth_fail"
        assert body.get("reserve_clicks", 0) == 0
    finally:
        ssm.put_parameter(
            Name=api_stack["parameter_name"],
            Value=json.dumps(_creds()),
            Type="SecureString",
            Overwrite=True,
        )
        lam.update_function_configuration(
            FunctionName=api_stack["function_name"],
            Environment={"Variables": _lambda_env(api_stack["parameter_name"])},
        )
        time.sleep(1)


def test_monday_2000_outside_hours_fails_the_lambda(api_stack):
    body = _invoke(
        api_stack["function_name"],
        {"source": "adhoc", "activity": "court2", "date": "2026-08-17", "time": "20:00"},
        allow_error=True,
    )
    assert body["status"] == "closed"
    assert body.get("reserve_clicks", 0) == 0


def _host_cancel(target: date, hhmm: str) -> None:
    generated = REPO / "generated" / "upace" / "python"
    sys.path.insert(0, str(generated))
    from booker.http import UpaceHttpBooker
    from booker.secrets import Credentials
    from booker.stub import BookingRequest

    mapping = _creds()
    UpaceHttpBooker().cancel(
        BookingRequest(
            activity_key="court2",
            activity_label="Court 2",
            target_date=target,
            hhmm=hhmm,
            duration_min=60,
            people=1,
            equipment_id=12739,
        ),
        Credentials(username=mapping[USERNAME_KEY], password=mapping[PASSWORD_KEY]),
    )


def test_live_book_then_cancel(api_stack):
    monday = date(2026, 8, 17)
    chosen = _find_open_slot(monday)
    if chosen is None:
        pytest.fail(f"no open Court 2 slot on {monday.isoformat()} for a live book")

    try:
        booked = _invoke(
            api_stack["function_name"],
            {"source": "adhoc", "activity": "court2", "date": monday.isoformat(), "time": chosen},
        )
        assert booked["status"] in {"booked", "already_held"}
        cancelled = _invoke(
            api_stack["function_name"],
            {
                "source": "adhoc",
                "activity": "court2",
                "date": monday.isoformat(),
                "time": chosen,
                "cancel": True,
            },
        )
        assert cancelled["status"] == "cancelled"
    finally:
        _host_cancel(monday, chosen)

