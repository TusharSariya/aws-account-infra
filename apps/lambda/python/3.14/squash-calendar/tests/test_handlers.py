from datetime import UTC, datetime, timedelta

import boto3
from moto import mock_aws
from test_calendar import data

from squash_calendar.handlers import claim, load, publish, release, serve
from squash_calendar.source import SourceError


class Source:
    def __init__(self, fail=False):
        self.fail = fail

    def collect(self, now, previous):
        if self.fail:
            raise SourceError("upstream unavailable")
        return data(now)


@mock_aws
def test_atomic_publication_outage_preservation_and_lease():
    client = boto3.client("s3", region_name="us-east-1")
    client.create_bucket(Bucket="squash-test")
    now = datetime(2026, 10, 12, 12, tzinfo=UTC)
    result = publish(client, "squash-test", Source(True), now)
    assert result["events"] == 8 and not result["enrichment_ok"]
    assert (
        serve({}, load(client, "squash-test")[0], now)["body"].count("BEGIN:VEVENT")
        == 8
    )
    publish(client, "squash-test", Source(), now)
    before = load(client, "squash-test")[0]
    publish(client, "squash-test", Source(True), now + timedelta(hours=1))
    after = load(client, "squash-test")[0]
    assert before["enrichment"] == after["enrichment"]
    assert before["events"] == after["events"]
    lease = claim(client, "squash-test", now)
    assert lease and claim(client, "squash-test", now) is None
    release(client, "squash-test", lease)
    assert claim(client, "squash-test", now)
