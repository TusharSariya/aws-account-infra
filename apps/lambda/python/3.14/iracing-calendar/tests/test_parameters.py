import json

import pytest
from botocore.stub import Stubber
from moto import mock_aws

from iracing_calendar.auth import AuthError, Parameters


@pytest.fixture
def parameters(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    with mock_aws():
        yield Parameters("/test/client", "/test/tokens")


def test_secure_standard_default_key_and_decrypted_latest_read(parameters):
    value = {"state": "exchange_pending"}
    with Stubber(parameters.api) as stub:
        stub.add_response(
            "put_parameter",
            {"Version": 2, "Tier": "Standard"},
            {
                "Name": "/test/tokens",
                "Value": json.dumps(value, separators=(",", ":")),
                "Type": "SecureString",
                "KeyId": "alias/aws/ssm",
                "Tier": "Standard",
                "Overwrite": True,
            },
        )
        stub.add_response(
            "get_parameter",
            {
                "Parameter": {
                    "Name": "/test/tokens",
                    "Type": "SecureString",
                    "Value": json.dumps(value),
                    "Version": 2,
                }
            },
            {"Name": "/test/tokens", "WithDecryption": True},
        )
        parameters.write("/test/tokens", value)
        assert parameters.read("/test/tokens") == value
        stub.assert_no_pending_responses()


def test_utf8_size_limit_rejects_before_request(parameters):
    # 4,096 UTF-8 bytes is accepted; multibyte characters count as bytes.
    assert len(parameters.serialize({"v": "x" * 4088}).encode()) == 4096
    with Stubber(parameters.api), pytest.raises(AuthError, match="4 KB"):
        parameters.write("/test/tokens", {"v": "é" * 2045})
    assert parameters.read("/test/tokens") == {}


def test_plaintext_or_malformed_values_are_rejected(parameters):
    for kind, value in [
        ("String", "{}"),
        ("SecureString", "not-json"),
        ("SecureString", "[]"),
    ]:
        parameters.api.put_parameter(
            Name="/test/tokens", Type=kind, Value=value, Overwrite=True
        )
        with pytest.raises(AuthError, match="Unable to read"):
            parameters.read("/test/tokens")


def test_errors_never_expose_parameter_contents(parameters):
    with Stubber(parameters.api) as stub:
        stub.add_client_error(
            "put_parameter",
            service_error_code="AccessDeniedException",
            service_message="private-token",
        )
        with pytest.raises(AuthError) as error:
            parameters.write("/test/tokens", {"refresh_token": "private-token"})
        assert "private-token" not in str(error.value)
        assert error.value.__suppress_context__


@pytest.mark.parametrize(
    "client_name,token_name",
    [("same", "same"), ("client", "tokens:2"), ("client:label", "tokens")],
)
def test_storage_names_cannot_select_historical_versions(client_name, token_name):
    with pytest.raises(AuthError, match="unversioned"):
        Parameters(client_name, token_name)
