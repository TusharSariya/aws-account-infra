from copy import deepcopy
from datetime import timedelta

import boto3
import httpx
from icalendar import Calendar
from moto import mock_aws
import pytest

from swim_calendar.source import class_events, create_source
from swim_calendar.handlers import load, publish, serve
from test_calendar import DAY, NOW, Source, lesson


def yoga(name='Yoga (12+)'):
    payload = lesson()
    payload['classes'][0].update(name=name, room_name='Studio (BTS)')
    return payload


@pytest.mark.parametrize('name', ['Yoga (12+)', 'Yoga / Pilates (12+)', 'Chair Yoga'])
def test_yoga_selection_preserves_published_title_and_excludes_swimming(name):
    payload = yoga(name)
    payload['classes'] += lesson()['classes']
    other = deepcopy(payload['classes'][0])
    other.update(id=999, gym_id=999)
    payload['classes'].append(other)
    events = class_events(payload, DAY, yoga=True)
    assert len(events) == 1
    assert events[0]['title'] == 'Yoga: ' + name
    assert events[0]['category'] == 'Yoga'
    assert events[0]['location'] == 'Ches Penney Family YMCA - Studio (BTS)'
    assert 'not registered' in events[0]['description']
    assert 'My Y Canada' in events[0]['description']
    assert [e['category'] for e in class_events(payload, DAY)] == ['Adult Lesson']


@pytest.mark.parametrize('name', ['Pilates (12+)', 'Cycle Fit', 'Adult Swim Lessons (12+)', 'Yogalates'])
def test_other_classes_are_excluded(name):
    assert class_events(yoga(name), DAY, yoga=True) == []


@pytest.mark.parametrize('field', ['cancelled', 'facility_closed'])
def test_cancelled_yoga_is_excluded_and_missing_state_rejected(field):
    payload = yoga()
    payload['classes'][0][field] = True
    assert class_events(payload, DAY, yoga=True) == []
    del payload['classes'][0][field]
    with pytest.raises(ValueError, match='Missing closure state'):
        class_events(payload, DAY, yoga=True)


@pytest.mark.parametrize('change', [
    {'date': '2026-09-25'}, {'start_day': '2026-09-25'},
    {'end_day': '2026-09-23'}, {'slot_id': None}, {'end_time': '18:00'},
])
def test_invalid_occurrence_fails_refresh(change):
    payload = yoga()
    payload['classes'][0].update(change)
    with pytest.raises(ValueError):
        class_events(payload, DAY, yoga=True)


def collector(respond):
    source = create_source('ymca_yoga')
    source.client.close()
    source.client = httpx.Client(base_url='https://upace.app/api/',
                                transport=httpx.MockTransport(respond))
    return source


def test_yoga_collects_each_date_without_pool_requests():
    calls = []
    def respond(request):
        calls.append(request)
        assert request.url.path == '/api/classes/list/unauth'
        assert request.url.params['university_id'] == '105'
        assert request.url.params['gym_id'] == '785'
        assert request.headers['X-SOURCE'] == 'EMBED'
        payload = yoga()
        payload['classes'][0]['date'] = request.url.params['date']
        return httpx.Response(200, json=payload)
    source = collector(respond)
    try:
        events = source.collect(DAY, DAY + timedelta(days=3))
        assert len(events) == len(calls) == 3
        assert calls[-1].url.params['date'] == '2026-09-26'
        with pytest.raises(TimeoutError):
            source.collect(DAY, DAY + timedelta(days=1), lambda: 10)
        assert len(calls) == 3
    finally:
        source.close()


@pytest.mark.parametrize('fault', ['http', 'partial', 'duplicate', 'malformed'])
@mock_aws
def test_yoga_publication_is_isolated_and_failed_refresh_preserves_snapshot(monkeypatch, fault):
    client = boto3.client('s3', region_name='us-east-1')
    for bucket in ('swimming-test', 'yoga-test'):
        client.create_bucket(Bucket=bucket)
    publish(client, 'swimming-test', Source(), NOW)
    swimming, _ = load(client, 'swimming-test')
    monkeypatch.setenv('CALENDAR_NAME', 'Ches Penney Yoga')
    monkeypatch.setenv('UID_DOMAIN', 'ymca-yoga-calendar')
    payload = yoga()
    source = collector(lambda request: httpx.Response(200, json=payload))
    try:
        # A one-day adapter keeps the fixture's occurrence date strict.
        class OneDay:
            def collect(self, *args):
                return source.collect(DAY, DAY + timedelta(days=1))
        publish(client, 'yoga-test', OneDay(), NOW)
        snapshot, _ = load(client, 'yoga-test')
        parsed = Calendar.from_ical(serve({}, snapshot)['body'])
        events = parsed.walk('VEVENT')
        assert str(parsed['X-WR-CALNAME']) == 'Ches Penney Yoga'
        assert len(events) == 1
        assert str(events[0]['UID']).endswith('@ymca-yoga-calendar')
        assert str(events[0]['SUMMARY']) == 'Yoga: Yoga (12+)'
        assert str(events[0]['TRANSP']) == 'TRANSPARENT'
        assert events[0].decoded('DTSTART').isoformat() == '2026-09-24T21:25:00+00:00'
        assert serve({'headers': {'If-None-Match': snapshot['etag']}}, snapshot)['statusCode'] == 304
        if fault == 'http':
            source.client.close()
            source.client = httpx.Client(base_url='https://upace.app/api/',
                transport=httpx.MockTransport(lambda request: httpx.Response(503)))
        elif fault == 'partial':
            payload['has_more'] = True
        elif fault == 'duplicate':
            payload['classes'] *= 2
        else:
            payload['classes'][0].pop('facility_closed')
        with pytest.raises((ValueError, httpx.HTTPStatusError)):
            publish(client, 'yoga-test', OneDay(), NOW)
        assert load(client, 'yoga-test')[0] == snapshot
        assert load(client, 'swimming-test')[0] == swimming
    finally:
        source.close()
