import base64
import json
from unittest.mock import MagicMock, patch

import pytest

from homelab_capacity.kube import Kube


def test_summary_uses_fixed_node_verified_tls_and_scoped_token():
    kube = Kube({"kubectl": "kubectl", "kubeconfig": "/private/coordinator"})
    credential = {
        "clusters": [
            {
                "cluster": {
                    "certificate-authority-data": base64.b64encode(
                        b"trusted-ca"
                    ).decode()
                }
            }
        ],
        "users": [{"user": {"token": "test-token"}}],
    }
    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps(
        {"node": {"nodeName": "talos-worker-01"}}
    ).encode()
    with (
        patch.object(kube, "run", return_value=json.dumps(credential)),
        patch("homelab_capacity.kube.ssl.create_default_context") as context,
        patch(
            "homelab_capacity.kube.urllib.request.urlopen", return_value=response
        ) as open_url,
    ):
        assert kube.stats("primary")["node"]["nodeName"] == "talos-worker-01"
        context.assert_called_once_with(cadata="trusted-ca")
        request = open_url.call_args.args[0]
        assert request.full_url == "https://10.0.0.222:10250/stats/summary"
        assert request.headers["Authorization"] == "Bearer test-token"
        assert open_url.call_args.kwargs == {
            "context": context.return_value,
            "timeout": 10,
        }
        with pytest.raises(ValueError, match="identity mismatch"):
            kube.stats("secondary")
        with pytest.raises(KeyError):
            kube.stats("unregistered")
