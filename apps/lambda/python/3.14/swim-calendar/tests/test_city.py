from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest

from swim_calendar.city import PaulReynolds, USER_AGENT, weekly_events
from swim_calendar.source import SwimmingSources
from swim_calendar.calendar import reconcile, render
from icalendar import Calendar

WEEK = date(2026, 9, 20)
FIXTURE = Path(__file__).with_name('fixtures') / 'paul-reynolds-week.html'


def test_real_week_times_categories_and_ics():
    events = weekly_events(FIXTURE.read_text(), WEEK)
    assert len(events) == 33  # The three Pop in Tot activities are excluded.
    day = [e for e in events if '2026-09-24-' in e['id']]
    assert len(day) == 4
    assert [(e['start'][11:16], e['end'][11:16]) for e in day] == [
        ('09:30', '11:20'), ('11:30', '12:20'), ('12:30', '16:20'), ('21:30', '22:20')]
    assert all(e['location'].startswith('Paul Reynolds') for e in events)
    now = datetime(2026, 9, 20, tzinfo=UTC)
    fresh = {e['id']: e for e in events}
    first = reconcile({}, fresh, now, now, date(2026, 10, 20))
    assert reconcile(first, fresh, now, now, date(2026, 10, 20)) == first
    parsed = Calendar.from_ical(render(first)).walk('VEVENT')
    assert len(parsed) == len({str(e['UID']) for e in parsed}) == 33
    assert all(str(e['TRANSP']) == 'TRANSPARENT' for e in parsed)


@pytest.mark.parametrize('change', [
    lambda s: s.replace('</html>', ''),
    lambda s: s.replace('Paul Reynolds Community Centre', 'Different pool'),
    lambda s: s.replace('09/27/2026', '10/04/2026'),
    lambda s: s.replace('hour-48-day-0', 'missing-grid'),
    lambda s: s.replace('calendar-bar-time', 'changed-time'),
    lambda s: s.replace('7:00 am - 8:50 am', '7:00 am - missing'),
    lambda s: s.replace('6 Lane &amp; Leisure', 'Unknown Swim'),
])
def test_invalid_pages_cannot_become_empty_calendars(change):
    with pytest.raises(ValueError):
        weekly_events(change(FIXTURE.read_text()), WEEK)


def test_collect_bounds_header_and_http_failure():
    requests = []
    def respond(request):
        requests.append(request)
        assert request.headers['user-agent'] == USER_AGENT
        assert request.url.params['StartDate'] == '09/20/2026'
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=FIXTURE.read_text())
    source = PaulReynolds()
    source.close()
    source.client = httpx.Client(base_url='https://calendar.stjohns.ca',
                                headers={'User-Agent': USER_AGENT}, transport=httpx.MockTransport(respond))
    try:
        result = source.collect(date(2026, 9, 24), date(2026, 9, 25))
        assert len(result) == 4
        assert len(requests) == 1
        with pytest.raises(TimeoutError):
            source.collect(WEEK, date(2026, 9, 25), lambda: 1)
    finally:
        source.close()
    source.client = httpx.Client(base_url='https://calendar.stjohns.ca',
                                transport=httpx.MockTransport(lambda _: httpx.Response(403)))
    try:
        with pytest.raises(httpx.HTTPStatusError):
            source.collect(WEEK, date(2026, 9, 25))
    finally:
        source.close()


def test_combined_failure_and_identity_collision():
    class Source:
        def __init__(self, result): self.result = result
        def collect(self, *args): return self.result
    class Failure:
        def collect(self, *args): raise ValueError('incomplete city response')
    combined = SwimmingSources.__new__(SwimmingSources)
    combined.sources = [Source({'ymca': {}}), Failure()]
    with pytest.raises(ValueError, match='incomplete'):
        combined.collect(WEEK, date(2026, 10, 20))
    combined.sources = [Source({'ymca': {}}), Source({'city': {}})]
    assert set(combined.collect(WEEK, date(2026, 10, 20))) == {'ymca', 'city'}
    combined.sources = [Source({'same': {}}), Source({'same': {}})]
    with pytest.raises(ValueError, match='Overlapping'):
        combined.collect(WEEK, date(2026, 10, 20))


def test_empty_week_explicit_cancellation_and_duplicate_rejection():
    from bs4 import BeautifulSoup
    html = FIXTURE.read_text()
    page = BeautifulSoup(html, 'html.parser')
    first = page.select_one('.day__event-meta')
    cancelled_path = first.select_one('a')['href']
    first.select_one('a').string = 'CANCELLED - 6 Lane & Leisure'
    events = weekly_events(str(page), WEEK)
    assert len(events) == 32
    assert not any(e['url'].endswith(cancelled_path) for e in events)
    page = BeautifulSoup(html, 'html.parser')
    page.body.append(BeautifulSoup(str(page.select_one('.day__event-meta')), 'html.parser'))
    with pytest.raises(ValueError, match='duplicate'):
        weekly_events(str(page), WEEK)
    page = BeautifulSoup(html, 'html.parser')
    for record in page.select('.day__event-meta'):
        record.decompose()
    assert weekly_events(str(page), WEEK) == []
    with pytest.raises(ValueError, match='outside'):
        weekly_events(html.replace('2026-09-24-', '2026-12-24-'), WEEK)
