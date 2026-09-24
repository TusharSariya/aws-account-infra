# Swimming calendars

Two independent public ICS services share this runtime and the
`modules/aws/swimming-calendar` OpenTofu module:

| Service | Deployment unit | Source | Sync function |
| --- | --- | --- | --- |
| Ches Penney Swimming | `aws-staging-swim-calendar` | Public Upace | `swim-calendar-sync` |
| Paul Reynolds Swimming | `aws-staging-paul-reynolds-swim-calendar` | City of St. John's calendar | `paul-reynolds-swim-calendar-sync` |

Each service has its own API Gateway hostname, sync/feed Lambdas, IAM roles,
private S3 snapshot and lease, daily schedule, failure queue and alarms. Each
exposes `GET /calendars/swimming.ics`. Neither feed contains the other facility's
events, and a failure refreshing one does not block the other. Both remain
separate from personal court reservations. The existing Ches Penney URL and
UIDs are preserved when resources move into the shared module using `moved` blocks.

`CALENDAR_SOURCE` selects exactly one source (`ymca` or `paul_reynolds`).
`CALENDAR_NAME`, `UID_DOMAIN` and `SERVICE_NAME` identify the deployment. Existing
YMCA defaults remain valid. IAM prevents either service accessing the other's
snapshot. Release objects have separate service prefixes even though both use
the same deterministic, locked ARM64 package.

## Sources

Ches Penney includes main-pool Lane Swim / Open, Calm Water Swim, and Adult Swim
Lessons (with published age limits). Play-pool sessions, restricted swims and
aquatic fitness classes are excluded. The collector queries both public Upace
endpoints for each date. It checks season boundaries, cancellations and closure
blocks. Recognized blocks subtract closed time from open windows; unfamiliar or
malformed blocks fail the refresh. It never logs in, books, or cancels anything.

Paul Reynolds includes Lane Swim, Open Swim, Leisure Swim and Therapeutic Swim.
Fitness classes and Pop in Tot are excluded. Dated
`https://calendar.stjohns.ca/prcc/Week?StartDate=MM/DD/YYYY` pages include complete
session durations. The dedicated city HTTP client sends a full browser
User-Agent, verified in real Lambda: changing only that header gives
403/200/403 for default/browser/default. No browser, cookies, login or PDF parsing
is required. Facility, weekly navigation, final grid cell, occurrence identities,
all durations and dates are validated. Unknown swimming titles, truncated pages
and HTTP errors preserve the previous snapshot. Holiday omissions and explicitly
cancelled entries are reconciled from published occurrences, without inventing
weekly recurrences.

These are activity options, not reservations or proof of free admission.

## Refresh and subscriptions

Each EventBridge Scheduler refreshes at 03:00 America/St_Johns every day, from
today through one calendar month ahead (exclusive; month-end clamps to the next
month's last day). Past events remain for 30 days.

A validated refresh atomically replaces a private S3 snapshot containing event
revisions and rendered ICS. Versioning permits recovery. Failed or incomplete
refreshes leave that service's previous calendar intact; conditional writes
prevent an older run replacing newer data. A 660-second expiring S3 lease
coalesces syncs and recovers after the 600-second Lambda timeout. The account has
10 Lambda slots and requires all 10 unreserved, so neither service reserves
concurrency. Snapshots contain no instructor/contact/attendee records.

Feeds support ETags and five-minute cache freshness. Before initialization they
return 503. Downloads do not trigger upstream refreshes. Public URLs require no
token. Subscribe using Apple Calendar's New Calendar Subscription, Outlook's
Subscribe from web, or Google Calendar's From URL. Importing a downloaded ICS is
a static copy. Events use UTC, stable UIDs, visible category prefixes, ICS
categories and transparent/free availability without reminders. Calendar clients
control polling and colours; we cannot force Outlook/Google to fetch immediately.

## Deployment

Everything is managed by the two OpenTofu units above. Plans build the zip from
locked dependencies using `scripts/swim-package.py`; apply uploads it under
`stable/<service-name>/<content-sha256>.zip` and deploys that exact artifact.
Existing court packaging and schedules are unchanged. Reapplying identical
inputs is a no-op. Each unit exports `calendar_url` and `sync_function`.

CI applies via the existing `apply` label and initializes each affected calendar
with a read-only sync. Manual IAM-authenticated refresh waits for completion:

```sh
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
  uv run --frozen --directory apps/lambda/python/3.14/swim-calendar \
  python -m swim_calendar sync --function swim-calendar-sync

AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
  uv run --frozen --directory apps/lambda/python/3.14/swim-calendar \
  python -m swim_calendar sync --function paul-reynolds-swim-calendar-sync
```

Independent sync/feed and failed-delivery alarms use the existing SNS/SES alert
path, identifying the affected service. Hourly health invocations check each
snapshot is less than 36 hours old. Logs retain 14 days, noncurrent snapshots
35 days. Unknown upstream shapes can require an adapter update; do not clear a
feed to bypass validation.

## Verification

```sh
uv run --frozen --directory apps/lambda/python/3.14/swim-calendar pytest
SWIM_LOCALSTACK_ENDPOINT=http://localhost:4566 \
  uv run --frozen --directory apps/lambda/python/3.14/swim-calendar pytest
```

CI runs unit tests without LocalStack. LocalStack integration is local-only;
tests create and clean up their own buckets. Live reads are opt-in and must not
be turned into booking tests. After deployment, parse both URLs, compare each
with its own source, test conditional GET and verify Newfoundland display times.
