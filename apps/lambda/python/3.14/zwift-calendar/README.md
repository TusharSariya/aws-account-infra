# Zwift race and special-event calendar

An hourly Lambda refreshes the signed-in rider's Zwift Racing Score, selects
eligible races and special-event rides over the next 14 days, and atomically publishes
two independent ICS subscriptions:

- `GET /calendars/zwift-banded.ics`: selected events with a Racing Score band.
- `GET /calendars/zwift-unbanded.ics`: selected events without a score band, including
  eligible individual time trials and retained special-event rides.

Both use the same 06:00–23:00 Newfoundland start window and Tour of Watopia
exclusion. Calendar clients choose their
own refresh frequency; the server refreshes at minute zero of every UTC hour.

## Selection and estimates

The service reads `scoring/current` and `scoring/max30` from Zwift. It uses the
30-day maximum where the event's access expression requires it. A confirmed
absence of both scores uses a provisional 100; API errors never become 100.
A failed score lookup can reuse a successful lookup for at most 24 hours and
raises an operational alert. Authentication, event-discovery failures, or older
score data preserve the last published calendar.

Cycling races and individual time trials are included with or without score bands.
Banded races must satisfy both the published range and supported access expression;
`Max` display bands use the 30-day maximum. For unbanded races, an authenticated
Zwift eligibility verdict can confirm legacy power/category restrictions. A false
verdict always excludes a group. Without a verdict, only unrestricted events or
locally understood entry expressions qualify. Missing score bands do not bypass
privacy, gender, age, category or other entry restrictions.

Recognized special-event group rides include Tour de Zwift, Zwift Games and
Zwift Big Spin. Tour of Watopia rides and races are explicitly excluded at the
user's request because their hourly starts make the calendar noisy. Recognition uses campaign names, event-series
names and explicit tag patterns in `campaigns.py`. New campaigns require an entry;
ordinary club rides, workouts, running, private events and team time trials remain
excluded. Announcements and on-demand activities without a scheduled start are not
calendar entries.

There is one calendar entry per event. Banded race choices use the lowest upper
score bound, then narrowest band. Unbanded races prefer the lowest advertised pace
among eligible groups, with a stable subgroup-ID tie-break; unknown pace is never
interpreted as zero or beginner difficulty. Descriptions explicitly distinguish
unbanded events from score-matched races.

Special rides choose the shortest eligible option using published distance, timed
duration, or explicit Short/Standard/Long labels. Lap counts on different routes
are not comparable. Ambiguous unlabeled route lengths are excluded and reported.
Starts must fall between 06:00 inclusive and 23:00 exclusive in
`America/St_Johns`, including daylight-saving changes. The filter uses each
subgroup's start, not the parent start or estimated finish. It applies to races
and special rides; an event starting before 23:00 may finish later.

Each entry uses its subgroup's start time. Time trials describe that time as the
session opening, because the rider's actual assigned start may be later. End
times use, in order:

1. Published timed-race duration.
2. Median of sampled, qualified finishers within 50 score points on the same
   route, distance, lap count and event type during the previous 90 days, with
   at least 10 finishes across two races.
3. An explicitly labelled 60-minute placeholder.

Only races consume the historical-result lookup budget. Special rides use their
published duration or the labelled fallback. The result-summary API samples leading finishers, not an entire field. Estimates
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
both rendered calendars, their separate ETags, a shared freshness timestamp and
transient lease metadata.
The public ICS exposes matching bands but no login, profile ID or exact score.
S3 is private, encrypted, versioned and requires TLS. A conditional 10-minute
lease serializes sync and authentication. Network requests have time, response
size and request-count limits; failures never publish partial discoveries.

Both feeds are committed together in one S3 write, so a partial refresh cannot
replace just one. Each feed supports its own ETag/304 and returns 503 before
initialization. Moving an event between bands preserves its UID and revision
history while removing it from the other feed. A separate
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
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli preview --output-dir /tmp/zwift-preview
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli sync
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar pytest
```

Deploy unit `aws-staging-zwift-calendar` uses the existing PR plan/apply workflow,
which synchronously initializes the calendar after apply. The new unit starts
with `schedule_enabled = false`. After successful initialization and feed review,
set it to true in `config/environments/aws/staging/zwift-calendar.tfvars` and apply
through the same workflow. Obtain the subscription URLs from the root's
`banded_calendar_url` and `unbanded_calendar_url` outputs. Subscribe to either or
both as separate calendars; a downloaded ICS import does not stay up to date.
The former combined `/calendars/zwift.ics` route is replaced before initial
deployment. Preview writes `zwift-banded.ics` and `zwift-unbanded.ics` in the
chosen output directory.

The preview/sync report includes separate next-seven-day and following-seven-day
counts for score-banded races, unbanded races and special rides. These count scheduled
start slots, not unique courses or campaign stages. Counts reflect currently published
inventory, so later-week counts may rise as organizers publish events.

Preview renews tokens and warms private caches under the lease but does not
publish or advance published revisions. Disable the schedule before credential
rotation or snapshot rollback. Restore an earlier S3 `current.json` version to
roll back a publication; rolling back code uses its content-addressed Lambda
artifact. See [contract evidence](../../../../../docs/zwift-api-contract.md).
