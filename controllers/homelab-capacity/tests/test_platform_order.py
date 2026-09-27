"""Every registered platform Deployment is scaled by the quiesce order."""

from homelab_capacity.platform import ORDER
from homelab_capacity.policy import PLATFORM


def test_every_platform_deployment_is_in_the_quiesce_order():
    missing = sorted(name for _, name in PLATFORM if name not in ORDER)
    assert missing == [], missing
    assert len(ORDER) == len(set(ORDER))


def test_playground_services_quiesce_before_the_cache_and_data_layers():
    assert ORDER.index("playground-ui") < ORDER.index("playground-router") < ORDER.index("nexus")
