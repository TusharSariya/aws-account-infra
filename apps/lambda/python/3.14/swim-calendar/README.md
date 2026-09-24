# St. John's Swimming

One public ICS feed, separate from personal court reservations. Includes main-pool
Lane Swim / Open, Calm Water Swim, and Adult Swim Lessons (with published age limits).
YMCA play-pool sessions, restricted swims and aquatic fitness classes are excluded.
Paul Reynolds Community Centre contributes Lane Swim, Open Swim, Leisure Swim,
and Therapeutic Swim. City fitness classes and Pop in Tot are excluded. Locations
distinguish the two facilities in the same general feed.
These are activity options, not reservations or proof of free admission.

EventBridge Scheduler refreshes at 03:00 America/St_Johns every day. The collector
queries both public Upace endpoints for each date from today through one calendar
month ahead (exclusive; month-end clamps to the next month's last day). It checks
season boundaries, cancellations and closure blocks. Paul Reynolds is read from
dated `/prcc/Week?StartDate=MM/DD/YYYY` pages across the same month window.
Its dedicated HTTP client sends a full browser User-Agent, verified in a real
Lambda A/B/A test (default 403, browser header 200, default 403). No browser,
cookies, login, or PDF parsing is required. Weekly navigation, facility, final
grid cell, every event duration, and occurrence dates are validated; unknown
swimming titles or HTTP errors fail the entire refresh. Only published dates
are imported, so holiday omissions are respected without inventing recurrence.
Both sources must finish before the combined snapshot is published. It never logs in, books, or
cancels anything. Recognized blocks subtract closed time from open windows;
unfamiliar or malformed blocks fail the refresh. Past events remain for 30 days.

A validated refresh atomically replaces a single private S3 snapshot containing
both event revisions and rendered ICS. Versioning permits recovery. Failed or
incomplete refreshes leave the previous calendar intact; conditional S3 writes
prevent an older overlapping run from replacing newer data. An expiring, conditionally written S3 lease coalesces concurrent syncs. The lease
lasts 660 seconds, longer than the Lambda 600-second timeout, and recovers after
abandoned work. This account has 10 Lambda slots and requires all 10 to remain
unreserved, so neither function reserves account concurrency. The snapshot has no instructor/contact/attendee data.

API Gateway serves GET /calendars/swimming.ics through a read-only Lambda, with
ETags and five-minute cache freshness. Before initialization it returns 503.
Downloads do not trigger Upace refreshes. The public URL requires no token.
Subscribe using Apple Calendar's New Calendar Subscription, Outlook's Subscribe
from web, or Google Calendar's From URL. Download/import alone is a static copy.
Events use UTC timestamps, stable UIDs, visible category prefixes, ICS categories,
and transparent/free availability, without reminders. Calendar clients control
polling and colours; we cannot force Outlook/Google to fetch immediately.

## Deployment

Everything is managed by the `aws-staging-swim-calendar` OpenTofu unit. The plan
builds an ARM64 zip from the locked dependencies using `scripts/swim-package.py`;
apply uploads it under `stable/swim-calendar/<content-sha256>.zip` and deploys that
exact artifact. This avoids a separate package-upload/tag race. Requires Python,
uv, and access to the locked public package index at plan time. Existing court
packaging and deployment are unchanged. Reapplying identical inputs is a no-op.

CI applies via the existing `apply` label and initializes the snapshot with a
read-only sync after deployment. Get the URL using the unit's `calendar_url` output.
A manual IAM-authenticated refresh waits for completion:

```sh
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
  uv run --frozen --directory apps/lambda/python/3.14/swim-calendar \
  python -m swim_calendar sync
```

Sync/feed failures and the shared delivery dead-letter queue alert through the
existing SNS/SES calendar alert path. An hourly health invocation checks that the
snapshot is less than 36 hours old; stale data alerts at the next hourly check.
Logs retain 14 days, noncurrent snapshots 35 days. An unknown upstream shape can
require an adapter update; do not clear the feed to bypass validation.

## Verification

```sh
uv run --frozen --directory apps/lambda/python/3.14/swim-calendar pytest
SWIM_LOCALSTACK_ENDPOINT=http://localhost:4566 \
  uv run --frozen --directory apps/lambda/python/3.14/swim-calendar pytest
```

LocalStack tests create and clean up their own bucket. Live reads are opt-in and
must not be turned into automatic booking tests. After deployment, parse the URL,
compare representative swims and lessons with Upace, test conditional GET, and
confirm each supported calendar client displays Newfoundland times correctly.
