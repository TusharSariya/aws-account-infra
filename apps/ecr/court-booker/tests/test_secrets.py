import json

from booker.secrets import PASSWORD_KEY, USERNAME_KEY, load_credentials


def test_load_credentials_from_ssm(monkeypatch):
    monkeypatch.setenv("CREDENTIALS_PARAMETER", "/staging/court-booker/my-y")
    captured: dict[str, object] = {}

    class Fake:
        def get_parameter(self, **kwargs):
            captured.update(kwargs)
            return {
                "Parameter": {
                    "Value": json.dumps({USERNAME_KEY: "user@example.com", PASSWORD_KEY: "stub"})
                }
            }

    monkeypatch.setattr("booker.secrets._ssm_client", lambda: Fake())
    creds = load_credentials()
    assert creds.username == "user@example.com"
    assert captured["Name"] == "/staging/court-booker/my-y"
    assert captured["WithDecryption"] is True
    assert "stub" not in repr(creds)


def test_load_credentials_from_env(monkeypatch):
    monkeypatch.delenv("CREDENTIALS_PARAMETER", raising=False)
    monkeypatch.setenv(USERNAME_KEY, "local@example.com")
    monkeypatch.setenv(PASSWORD_KEY, "local-pass")
    monkeypatch.setattr("booker.secrets.load_dotenv_files", lambda: None)
    creds = load_credentials()
    assert creds.username == "local@example.com"
