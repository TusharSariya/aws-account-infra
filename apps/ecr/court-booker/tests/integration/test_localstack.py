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
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import boto3
import pytest

from booker.schedule import resolve_weekly_target

ENDPOINT = os.environ.get("LOCALSTACK_ENDPOINT", "http://localhost:4566")
REGION = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
ROOT = Path(__file__).resolve().parents[2]
TZ = ZoneInfo("America/St_Johns")
WEEKLY_PAYLOAD = {
    "source": "weekly",
    "activity": "court1",
    "weekday": "Mon",
    "time": "18:00",
    "wait": False,
}


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


pytestmark = pytest.mark.skipif(not _localstack_up(), reason="LocalStack is not running on :4566")


def _lambda_env(parameter_name: str, scenario: str = "success") -> dict[str, str]:
    return {
        "BOOKER_BROWSER": "stub",
        "BOOKER_STUB_SCENARIO": scenario,
        "BOOKER_SKIP_WAIT": "1",
        "BOOKER_NOW": "2026-08-14T17:58:00-02:30",
        "CREDENTIALS_PARAMETER": parameter_name,
        "BOOKINGS_PATH": "bookings.yaml",
    }


def _package_zip(work: Path) -> Path:
    staging = work / "pkg"
    staging.mkdir()
    shutil.copytree(ROOT / "booker", staging / "booker", ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy(ROOT / "bookings.yaml", staging / "bookings.yaml")
    machine = platform.machine().lower()
    pip_platform = "manylinux2014_aarch64" if machine in {"arm64", "aarch64"} else "manylinux2014_x86_64"
    subprocess.check_call(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "pyyaml==6.0.2",
            "--platform",
            pip_platform,
            "--python-version",
            "3.12",
            "--implementation",
            "cp",
            "--only-binary=:all:",
            "-t",
            str(staging),
            "-q",
        ],
    )
    dest = work / "booker.zip"
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in staging.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and ".dist-info" not in path.parts:
                archive.write(path, path.relative_to(staging).as_posix())
    return dest


@pytest.fixture(scope="module")
def stack(tmp_path_factory):
    work = tmp_path_factory.mktemp("booker-zip")
    zip_path = _package_zip(work)
    suffix = uuid.uuid4().hex[:8]
    parameter_name = f"/staging/court-booker/my-y-{suffix}"
    function_name = f"court-booker-{suffix}"
    role_arn = "arn:aws:iam::000000000000:role/court-booker-lambda"
    ssm = _client("ssm")
    lam = _client("lambda")
    ssm.put_parameter(
        Name=parameter_name,
        Value=json.dumps(
            {"my_YMCA_username": "user@example.com", "my_YMCA_password": "stub"}
        ),
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
            Timeout=30,
            Environment={"Variables": _lambda_env(parameter_name)},
        )
    try:
        lam.get_waiter("function_active").wait(FunctionName=function_name)
    except Exception:
        time.sleep(2)
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
    body = json.loads(response["Payload"].read().decode("utf-8"))
    if allow_error:
        assert response.get("FunctionError") == "Unhandled", body
        return json.loads(body["errorMessage"])
    assert "FunctionError" not in response, body
    return body


def test_lambda_reads_secret_and_books_monday_72h_ahead(stack):
    friday = datetime(2026, 8, 14, 17, 58, tzinfo=TZ)
    expected = resolve_weekly_target(weekday="Mon", hhmm="18:00", now=friday).target_date.isoformat()
    body = _invoke(stack["function_name"], WEEKLY_PAYLOAD)
    assert body["status"] == "booked"
    assert body["target_date"] == expected
    assert body["reserve_clicks"] == 1


def test_auth_fail_does_not_reserve(stack):
    lam = _client("lambda")
    lam.update_function_configuration(
        FunctionName=stack["function_name"],
        Environment={"Variables": _lambda_env(stack["parameter_name"], scenario="auth_fail")},
    )
    time.sleep(1)
    body = _invoke(stack["function_name"], WEEKLY_PAYLOAD, allow_error=True)
    assert body["status"] == "auth_fail"
    assert body["reserve_clicks"] == 0
    lam.update_function_configuration(
        FunctionName=stack["function_name"],
        Environment={"Variables": _lambda_env(stack["parameter_name"])},
    )


def test_scheduler_target_has_zero_retries_and_same_payload(stack):
    scheduler = _client("scheduler")
    lam = _client("lambda")
    iam = _client("iam")
    role_name = f"court-booker-scheduler-{stack['suffix']}"
    try:
        iam.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=json.dumps(
                {
                    "Version": "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {"Service": "scheduler.amazonaws.com"},
                            "Action": "sts:AssumeRole",
                        }
                    ],
                }
            ),
        )
    except Exception:
        pass
    iam.put_role_policy(
        RoleName=role_name,
        PolicyName="invoke",
        PolicyDocument=json.dumps(
            {
                "Version": "2012-10-17",
                "Statement": [{"Effect": "Allow", "Action": "lambda:InvokeFunction", "Resource": "*"}],
            }
        ),
    )
    function_arn = lam.get_function(FunctionName=stack["function_name"])["Configuration"]["FunctionArn"]
    role_arn = iam.get_role(RoleName=role_name)["Role"]["Arn"]
    name = f"court-booker-weekly-{stack['suffix']}"
    try:
        scheduler.create_schedule(
            Name=name,
            ScheduleExpression="cron(58 17 ? * FRI *)",
            ScheduleExpressionTimezone="America/St_Johns",
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": function_arn,
                "RoleArn": role_arn,
                "Input": json.dumps(WEEKLY_PAYLOAD),
                "RetryPolicy": {"MaximumRetryAttempts": 0, "MaximumEventAgeInSeconds": 60},
            },
            State="DISABLED",
        )
    except Exception as exc:
        pytest.skip(f"EventBridge Scheduler not available: {exc}")
    try:
        got = scheduler.get_schedule(Name=name)
        assert got["Target"]["RetryPolicy"]["MaximumRetryAttempts"] == 0
        assert json.loads(got["Target"]["Input"]) == WEEKLY_PAYLOAD
        body = _invoke(stack["function_name"], json.loads(got["Target"]["Input"]))
        assert body["status"] == "booked"
        assert body["reserve_clicks"] == 1
    finally:
        try:
            scheduler.delete_schedule(Name=name)
        except Exception:
            pass
