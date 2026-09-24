import hashlib
import io
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))
from cache import cache_model


def response(content):
    result = io.BytesIO(content)
    result.url = "https://example.test/model"
    return result


def test_cache_is_verified_and_reused(tmp_path):
    target = tmp_path / "model"
    digest = hashlib.sha256(b"valid").hexdigest()
    with patch("urllib.request.urlopen", return_value=response(b"valid")) as fetch:
        assert cache_model("https://example.test/model", digest, target)
        assert not cache_model("https://example.test/model", digest, target)
        assert fetch.call_count == 1
    assert target.read_bytes() == b"valid"


def test_bad_download_preserves_existing_cache_and_removes_temporary(tmp_path):
    target = tmp_path / "model"
    target.write_bytes(b"existing")
    with patch("urllib.request.urlopen", return_value=response(b"corrupt")):
        with pytest.raises(ValueError, match="checksum"):
            cache_model("https://example.test/model", "a" * 64, target)
    assert target.read_bytes() == b"existing"
    assert list(tmp_path.iterdir()) == [target]
