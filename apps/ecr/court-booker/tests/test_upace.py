from booker.upace import LAMBDA_CHROMIUM_ARGS, in_lambda


def test_in_lambda_follows_runtime_env(monkeypatch):
    monkeypatch.delenv("AWS_LAMBDA_FUNCTION_NAME", raising=False)
    assert in_lambda() is False
    monkeypatch.setenv("AWS_LAMBDA_FUNCTION_NAME", "court-booker")
    assert in_lambda() is True


def test_lambda_chromium_args_disable_shm_and_sandbox():
    assert "--disable-dev-shm-usage" in LAMBDA_CHROMIUM_ARGS
    assert "--no-sandbox" in LAMBDA_CHROMIUM_ARGS
    assert "--single-process" in LAMBDA_CHROMIUM_ARGS
