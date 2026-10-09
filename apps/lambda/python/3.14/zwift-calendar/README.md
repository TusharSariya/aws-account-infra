# Zwift racing calendar

An hourly Lambda refreshes the signed-in rider's Zwift Racing Score, selects
eligible advertised score bands over the next 14 days, and atomically publishes
an ICS subscription at `GET /calendars/zwift.ics`. Calendar clients choose their
own refresh frequency; the server refreshes at minute zero of every UTC hour.

## Selection and estimates

The service reads `scoring/current` and `scoring/max30` from Zwift. It uses the
30-day maximum where the event's access expression requires it. A confirmed
absence of both scores uses a provisional 100; API errors never become 100.
A failed score lookup can reuse a successful lookup for at most 24 hours and
raises an operational alert. Authentication, event-discovery failures, or older
score data preserve the last published calendar.

Cycling races and individual time trials qualify only when an advertised score
band and a supported access expression both accept the rider. Team events,
private events, unscored categories, unsupported restrictions, and malformed
bands are excluded. Gender and profile restrictions in supported expressions
are checked. The narrow safe expression parser does not execute upstream code.
There is no route, time-of-day, series, or band-width preference. Overlapping
eligible bands resolve to the lowest upper bound, then narrowest band.

Each entry uses its subgroup's start time. Time trials describe that time as the
session opening, because the rider's actual assigned start may be later. End
times use, in order:

1. Published timed-race duration.
2. Median of sampled, qualified finishers within 50 score points on the same
   route, distance, lap count and event type during the previous 90 days, with
   at least 10 finishes across two races.
3. An explicitly labelled 60-minute placeholder.

The result-summary API samples leading finishers, not an entire field. Estimates
are labelled accordingly and may be optimistic. History bootstraps from recurring
parent events and previously observed races; at most 12 historical events are
queried per run. Only anonymous score/time histograms are stored, never finisher
names or profile IDs. Events removed or no longer eligible disappear from the
subscription. Stable event/subgroup UIDs and revision timestamps avoid duplicates.

## Authentication and storage

SSM Standard SecureStrings `/staging/zwift-calendar/credentials` and
`/staging/zwift-calendar/tokens` use `alias/aws/ssm`. Values are provisioned outside
OpenTofu and never enter infrastructure state. Only the sync role reads them; it
can write only the token parameter. Tokens persist before use, and an uncertain
exchange leaves a pending marker instead of retrying the old refresh token.

S3 `private.json` holds the rider score, eligibility fields, anonymous history,
and revision cache. The feed role can read only `current.json`, which contains
the rendered calendar, ETag, freshness timestamp and transient lease metadata.
The public ICS exposes matching bands but no login, profile ID or exact score.
S3 is private, encrypted, versioned and requires TLS. A conditional 10-minute
lease serializes sync and authentication. Network requests have time, response
size and request-count limits; failures never publish partial discoveries.

The feed supports ETag/304 and returns 503 before initialization. A separate
hourly health invocation alerts when the last successful publication is more
than three hours old. Lambda errors and delivery failures use the existing
calendar SNS alert channel.

## Operator commands and rollout

From the repository root, use the existing AWS operator profile and region:

```sh
export AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1
export SNAPSHOT_BUCKET=zwift-calendar-992382747916-us-east-1
# Hidden password prompt; also clears cached tokens. Disable cron during rotation.
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli credentials
# After infrastructure exists:
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli auth-check
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli preview --output /tmp/zwift-preview.ics
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli sync
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar pytest
```

Deploy unit `aws-staging-zwift-calendar` uses the existing PR plan/apply workflow,
which synchronously initializes the calendar after apply. The new unit starts
with `schedule_enabled = false`. After successful initialization and feed review,
set it to true in `config/environments/aws/staging/zwift-calendar.tfvars` and apply
through the same workflow. Obtain the subscription URL from the root's
`calendar_url` output. Add it as a calendar URL subscription, rather than importing
a one-time downloaded file.

Preview renews tokens and warms private caches under the lease but does not
publish or advance published revisions. Disable the schedule before credential
rotation or snapshot rollback. Restore an earlier S3 `current.json` version to
roll back a publication; rolling back code uses its content-addressed Lambda
artifact. See [contract evidence](../../../../../docs/zwift-api-contract.md).
