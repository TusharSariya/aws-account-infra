from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
import os
import uuid

import boto3
from botocore.exceptions import ClientError
from icalendar import Calendar
from moto import mock_aws
import pytest

from swim_calendar.source import (Upace, equipment_events, class_events, month_end, instant, rows)
from swim_calendar.calendar import reconcile, render
from swim_calendar.handlers import load, publish, serve

DAY = date(2026, 9, 24)
NOW = datetime(2026, 9, 24, 4, tzinfo=UTC)


def equipment():
    return {"success": True, "schedule": [{"equipment": {"id": 14084, "gym_id": 785,
            "room_id": 6091, "room_name": "Main Pool", "name": "2-Lane Swim / Open"},
            "slots": [{"id": 123, "day_of_week": "Thu", "start_time": "10:10", "end_time": "13:55"}],
            "block_schedules": []}]}


def lesson():
    return {"success": True, "classes": [{"id": 92774, "slot_id": 456, "gym_id": 785,
            "name": "Adult Swim Lessons (12+)", "date": str(DAY), "start_time": "18:55:00",
            "end_time": "19:25:00", "start_day": "2026-09-16", "end_day": "2027-06-24",
            "room_name": "Main Pool", "cancelled": False, "facility_closed": False}]}


def fresh():
    return {x['id']: x for x in equipment_events(equipment(), DAY) + class_events(lesson(), DAY)}


class Source:
    def __init__(self, events=None):
        self.events = fresh() if events is None else events

    def collect(self, *args):
        return deepcopy(self.events)


def test_categories_and_exclusions():
    payload = equipment()
    other = deepcopy(payload['schedule'][0])
    other['equipment']['gym_id'] = 999
    payload['schedule'].append(other)
    assert len(equipment_events(payload, DAY)) == 1
    payload['schedule'][0]['equipment'].update(room_id=6092, name='Open Swim (Play Pool)')
    assert equipment_events(payload, DAY) == []
    payload['schedule'][0]['equipment'].update(room_id=7421, name='Open Swim (Female Only Swim)')
    assert equipment_events(payload, DAY) == []
    payload['schedule'][0]['equipment']['name'] = 'Open Swim (Calm Water Swim)'
    assert equipment_events(payload, DAY)[0]['category'] == 'Calm Water'
    assert class_events(lesson(), DAY)[0]['category'] == 'Adult Lesson'
    for name in ['Aqua Fit (12+)', 'Youth Swim Lessons', 'Deep Water Fitness']:
        payload = lesson()
        payload['classes'][0]['name'] = name
        assert class_events(payload, DAY) == []


@pytest.mark.parametrize('field', ['cancelled', 'facility_closed'])
def test_lesson_cancellation(field):
    payload = lesson()
    payload['classes'][0][field] = True
    assert class_events(payload, DAY) == []
    del payload['classes'][0][field]
    with pytest.raises(ValueError):
        class_events(payload, DAY)


@pytest.mark.parametrize('payload', [{}, {'success': False, 'classes': []},
    {'success': True, 'classes': None}, {'success': True, 'classes': [], 'has_more': True},
    {'success': True, 'classes': [], 'total': 1}])
def test_malformed_or_partial(payload):
    with pytest.raises(ValueError):
        rows(payload, 'classes')


def test_unknown_closure_fails_closed():
    payload = equipment()
    payload['schedule'][0]['block_schedules'] = [{'unknown': True}]
    with pytest.raises((ValueError, KeyError)):
        equipment_events(payload, DAY)


def test_dst_and_month_boundaries():
    assert instant(date(2026, 9, 24), '11:00') == '2026-09-24T13:30:00+00:00'
    assert instant(date(2026, 12, 24), '11:00') == '2026-12-24T14:30:00+00:00'
    assert month_end(date(2026, 1, 31)) == date(2026, 2, 28)
    assert month_end(date(2028, 1, 31)) == date(2028, 2, 29)
    assert month_end(date(2026, 12, 24)) == date(2027, 1, 24)
    with pytest.raises(ValueError):
        instant(date(2026, 3, 8), '02:30')
    with pytest.raises(ValueError):
        instant(date(2026, 11, 1), '01:30')


def test_revisions_identity_removal_and_return():
    before = reconcile({}, fresh(), NOW, NOW, month_end(DAY))
    again = reconcile(before, fresh(), NOW + timedelta(hours=1), NOW, month_end(DAY))
    assert before == again
    assert render(before) == render(again)
    changed = fresh()
    key = next(iter(changed))
    changed[key]['end'] = '2026-09-24T17:00:00+00:00'
    after = reconcile(before, changed, NOW + timedelta(hours=2), NOW, month_end(DAY))
    assert after[key]['sequence'] == 1
    removed = reconcile(after, {}, NOW + timedelta(hours=3), NOW, month_end(DAY))
    assert len(Calendar.from_ical(render(removed)).walk('VEVENT')) == 0
    returned = reconcile(removed, fresh(), NOW + timedelta(hours=4), NOW, month_end(DAY))
    assert returned[key]['sequence'] == 3
    a = Calendar.from_ical(render(before)).walk('VEVENT')
    b = Calendar.from_ical(render(returned)).walk('VEVENT')
    assert [str(e['UID']) for e in a] == [str(e['UID']) for e in b]
    assert all(str(e['TRANSP']) == 'TRANSPARENT' for e in b)
    assert all(not e.walk('VALARM') for e in b)


def test_retention():
    before = reconcile({}, fresh(), NOW, NOW, month_end(DAY))
    later = NOW + timedelta(days=31)
    assert reconcile(before, {}, later, later, month_end(later.date())) == {}


@mock_aws
def test_atomic_snapshot_and_conditional_responses():
    client = boto3.client('s3', region_name='us-east-1')
    client.create_bucket(Bucket='swim-test')
    assert serve({}, load(client, 'swim-test')[0])['statusCode'] == 503
    publish(client, 'swim-test', Source(), NOW)
    previous, etag = load(client, 'swim-test')
    response = serve({}, previous)
    assert response['statusCode'] == 200
    assert len(Calendar.from_ical(response['body']).walk('VEVENT')) == 2
    assert serve({'headers': {'If-None-Match': 'W/' + previous['etag']}}, previous)['statusCode'] == 304
    publish(client, 'swim-test', Source(), NOW + timedelta(hours=1))
    current, _ = load(client, 'swim-test')
    assert current['etag'] == previous['etag']
    class Failure:
        def collect(self, *args):
            raise ValueError('invalid upstream')
    with pytest.raises(ValueError):
        publish(client, 'swim-test', Failure(), NOW)
    assert load(client, 'swim-test')[0] == current
    publish(client, 'swim-test', Source({}), NOW)
    empty, _ = load(client, 'swim-test')
    assert len(Calendar.from_ical(empty['ics']).walk('VEVENT')) == 0


def test_collector_checks_each_date_and_budget():
    source = Upace()
    calls = []
    def get(path, params, header):
        calls.append(params)
        return {'success': True, 'schedule': []} if 'equipment' in path else {'success': True, 'classes': []}
    source.get = get
    try:
        assert source.collect(DAY, DAY + timedelta(days=3)) == {}
        assert len(calls) == 6
        assert calls[-1]['date'] == '2026-09-26'
        with pytest.raises(TimeoutError):
            source.collect(DAY, DAY + timedelta(days=1), lambda: 10)
    finally:
        source.close()


def test_localstack_snapshot_versioning_and_fencing():
    endpoint = os.environ.get('SWIM_LOCALSTACK_ENDPOINT')
    if not endpoint:
        pytest.skip('isolated LocalStack test')
    client = boto3.client('s3', endpoint_url=endpoint, region_name='us-east-1',
                          aws_access_key_id='test', aws_secret_access_key='test')
    bucket = 'swim-' + uuid.uuid4().hex
    client.create_bucket(Bucket=bucket)
    try:
        client.put_bucket_versioning(Bucket=bucket, VersioningConfiguration={'Status': 'Enabled'})
        publish(client, bucket, Source(), NOW)
        previous, etag = load(client, bucket)
        from concurrent.futures import ThreadPoolExecutor
        from threading import Barrier
        from swim_calendar.handlers import claim, release
        gate = Barrier(6)
        def attempt(_):
            gate.wait()
            return claim(client, bucket, NOW)
        with ThreadPoolExecutor(max_workers=6) as pool:
            winners = [value for value in pool.map(attempt, range(6)) if value]
        assert len(winners) == 1
        release(client, bucket, winners[0])
        publish(client, bucket, Source({}), NOW + timedelta(hours=1))
        with pytest.raises(ClientError) as err:
            client.put_object(Bucket=bucket, Key='current.json', Body=b'{}', IfMatch=etag)
        assert err.value.response['Error']['Code'] == 'PreconditionFailed'
        versions = client.list_object_versions(Bucket=bucket)['Versions']
        assert len([v for v in versions if v['Key'] == 'current.json']) == 2
        assert load(client, bucket)[0]['ics'] != previous['ics']
    finally:
        versions = client.list_object_versions(Bucket=bucket).get('Versions', [])
        if versions:
            client.delete_objects(Bucket=bucket, Delete={'Objects': [{'Key': v['Key'], 'VersionId': v['VersionId']} for v in versions]})
        client.delete_bucket(Bucket=bucket)


def test_closure_subtracts_partial_windows_and_full_cancellation():
    payload = equipment()
    payload['schedule'][0]['block_schedules'] = [dict(block_schedule_id=99, day_of_week='Thu', start_time='11:00', end_time='12:00')]
    events = equipment_events(payload, DAY)
    assert len(events) == 2
    assert events[0]['end'] == '2026-09-24T13:30:00+00:00'
    assert events[1]['start'] == '2026-09-24T14:30:00+00:00'
    payload['schedule'][0]['block_schedules'][0].update(start_time='00:00', end_time='23:59')
    assert equipment_events(payload, DAY) == []


@mock_aws
def test_older_collection_cannot_replace_newer_publication():
    client = boto3.client('s3', region_name='us-east-1')
    client.create_bucket(Bucket='swim-test')
    publish(client, 'swim-test', Source(), NOW)
    class OverlappingSource:
        def collect(self, *args):
            publish(client, 'swim-test', Source({}), NOW + timedelta(minutes=1))
            return fresh()
    with pytest.raises(ClientError):
        publish(client, 'swim-test', OverlappingSource(), NOW)
    snapshot, _ = load(client, 'swim-test')
    assert snapshot['last_success'] == (NOW + timedelta(minutes=1)).isoformat()
    assert Calendar.from_ical(snapshot['ics']).walk('VEVENT') == []


def test_lesson_wrong_date_and_invalid_season_rejected():
    payload = lesson()
    payload['classes'][0]['date'] = '2026-09-25'
    with pytest.raises(ValueError):
        class_events(payload, DAY)
    payload = lesson()
    payload['classes'][0]['end_day'] = '2026-08-01'
    with pytest.raises(ValueError):
        class_events(payload, DAY)


def test_health_check_alerts_on_stale_snapshot(monkeypatch):
    from swim_calendar import handlers
    monkeypatch.setenv('SNAPSHOT_BUCKET', 'test')
    monkeypatch.setattr(handlers, 's3', lambda: None)
    monkeypatch.setattr(handlers, 'load', lambda *args: (None, None))
    with pytest.raises(RuntimeError, match='36 hours'):
        handlers.feed({'health': True}, None)
    monkeypatch.setattr(handlers, 'load', lambda *args: ({'last_success': datetime.now(UTC).isoformat()}, None))
    assert handlers.feed({'health': True}, None) == {'status': 'healthy'}
    monkeypatch.setattr(handlers, 'load', lambda *args: ({'last_success': (datetime.now(UTC) - timedelta(hours=37)).isoformat()}, None))
    with pytest.raises(RuntimeError, match='36 hours'):
        handlers.feed({'health': True}, None)


@mock_aws
def test_refresh_lease_coalesces_and_recovers_after_timeout():
    from swim_calendar.handlers import claim, release
    client = boto3.client('s3', region_name='us-east-1')
    client.create_bucket(Bucket='swim-test')
    first = claim(client, 'swim-test', NOW)
    assert first
    assert claim(client, 'swim-test', NOW + timedelta(seconds=30)) is None
    successor = claim(client, 'swim-test', NOW + timedelta(seconds=661))
    assert successor and successor != first
    release(client, 'swim-test', first)
    assert claim(client, 'swim-test', NOW + timedelta(seconds=662)) is None
    release(client, 'swim-test', successor)
    assert claim(client, 'swim-test', NOW + timedelta(seconds=663))


@mock_aws
def test_deployments_keep_independent_snapshots_and_failures(monkeypatch):
    from swim_calendar import handlers
    client = boto3.client('s3', region_name='us-east-1')
    client.create_bucket(Bucket='ymca-test')
    client.create_bucket(Bucket='city-test')
    monkeypatch.setattr(handlers, 's3', lambda: client)
    publish(client, 'ymca-test', Source(), NOW)
    ymca, _ = load(client, 'ymca-test')
    monkeypatch.setenv('CALENDAR_NAME', 'Paul Reynolds Swimming')
    monkeypatch.setenv('UID_DOMAIN', 'paul-reynolds-swim-calendar')
    publish(client, 'city-test', Source({}), NOW)
    city, _ = load(client, 'city-test')
    assert 'Paul Reynolds Swimming' in city['ics']
    assert 'Ches Penney Swimming' in ymca['ics']
    class Failure:
        def collect(self, *args): raise ValueError('city unavailable')
    with pytest.raises(ValueError):
        publish(client, 'city-test', Failure(), NOW)
    assert load(client, 'ymca-test')[0] == ymca
    assert load(client, 'city-test')[0] == city
