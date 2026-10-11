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
which synchronously initializes the calendar after apply. The initial deployment
used `schedule_enabled = false`; authenticated sync and both live feeds were
verified before enabling hourly refresh. The staging configuration now uses
`schedule_enabled = true`. For a new rollout, repeat that disabled-first sequence
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

## Historical duration backfill

`zwift-calendar-history` is a separate batch Lambda. Every three hours at minute
20 UTC it resumes historical discovery and samples comparable finishers. The
hourly calendar sync writes `history/targets.json`, reads `history/state.json`,
and publishes improved durations through the same two subscription URLs. It no
longer fetches historical results inline. The worker never publishes calendars.

The worker imports the legacy history once. Its versioned private state includes
anonymous score/time bins, pending event/subgroup work, discovery cursors and
admission counters. Only qualified, unflagged finishers count. Estimates still
require ten finishes from two races on the same route/distance/laps/type within
50 score points. The verified upstream summary is sampled, not a complete finish
distribution. Insufficient evidence keeps the labeled 60-minute placeholder.

Bounds: 512 MB Arm, 180-second Lambda timeout, 150-second upstream deadline,
120 HTTP attempts/run, two attempts/second, at most eight admitted runs per UTC
day and 248/month (manual invocations share these limits). A three-hour slot is
reserved durably before upstream calls. Invocation retries are disabled. HTTP
429 saves a cooldown. Work state is capped at 5 MiB and 10,000 queued events,
with at most five state writes/run; obsolete unused evidence is evicted first.
History expires after 90 days. The existing 35-day S3 noncurrent-version lifecycle
also bounds historical checkpoint storage. Logs retain seven days.

The account has a concurrency quota of ten and requires ten unreserved slots,
so reserved concurrency one cannot be configured. The shared conditional S3 lease
serializes backfill, authentication and calendar writes; overlapping workers exit
immediately. Schedule offset avoids the hourly publisher. Credential values never
enter IaC, fixtures or logs. No new public HTTP endpoint is added.

Worst scheduled compute allowance is 248 x 180 x 0.5 = 22,320 GB-seconds/month,
approximately US$0.30 at Arm pricing before free-tier credits. Budget another
US$0.30-0.40 for bounded versioned S3 storage/requests, logging and one alarm.
This is incremental cost, not a hard billing cap or the whole calendar bill.

```sh
# Uses the same AWS operator environment as the commands above.
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli backfill
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli backfill-status
```

Rollout: keep `history_enabled = false`, deploy through the PR apply workflow
(which initializes targets through the normal calendar sync), run one bounded
batch, inspect coverage and budgets, then sync and verify both feeds. Enable the
schedule in IaC after verification. Enabled feed health checks alert if remaining
placeholders have no successful worker check-in for 24 hours. Inspect the batch
summary at 24/72 hours; limited evidence is not a promise of complete coverage.
Rollback disables `history_enabled`; cached estimates and subscriptions continue.

## Historical turnout filter

Both feeds omit races whose arithmetic mean is below 10 qualified, unflagged
finishers in the selected division. Exactly 10 is retained. The mean uses the
latest two to six available comparable editions within 90 days, following Zwift's
recurring-parent links and matching event type, score band (or legacy label and
pace bounds), weekday and subgroup start time in Newfoundland. Course changes
within a recurring series do not alone invalidate turnout. Editions must be at
least 24 hours old. Unknown turnout remains visible and is explicitly labelled;
ordinary special rides are unaffected.

Descriptions include the average and number of editions. Known averages also
appear in `X-ZWIFT-AVERAGE-FINISHERS` and `X-ZWIFT-TURNOUT-EDITIONS`. Preview/sync
reports include `before_turnout_filter` and `turnout.filtered`, with separate
banded/unbanded exclusion counts plus known/unknown coverage. Unknown counts
distinguish pending lookups, missing parent links and insufficient comparable
history. Collection prioritizes two editions across races before deepening to six.
Filtered races stay
in historical collection targets so subsequent evidence can restore them.

The existing worker shares its 120-request budget between turnout collection
(first approximately 40 requests, completing an in-flight subgroup if needed)
and duration history. Full results use `start` pagination in pages of 25 and
must reach an empty page before a count is trusted; partial responses, failures,
repeated riders and pagination limits never become zero. Only complete aggregate
counts are persisted, without rider names or identifiers. Coverage builds over
scheduled runs. Historical discovery retains its cursor when hourly targets
change; earlier pages are revisited in the next complete scan.

## One-off AWS turnout bootstrap

The manually started `zwift-calendar-history-bootstrap` Standard Step Functions
workflow runs the existing history Lambda repeatedly. This is separate from the
small three-hourly maintenance pass. It freezes the current race targets in
`history/state.json` under `bootstrap`, collects up to six comparable editions
per race (two across the inventory first), and refreshes both calendars on exit.
Its final execution output contains the frozen-target coverage report and the
new calendar report, including the current number filtered below ten finishers.
Duration sampling remains the scheduled worker's responsibility.

Each execution reserves at most 100 batches of 120 requests (12,000 attempts,
including authentication and retries), at two requests/second. Batches wait at
least 60 seconds, respect upstream cooldowns, share the calendar/authentication
lease, and checkpoint aggregate counts into the existing private S3 cache.
The execution keeps its targets across hourly syncs; another active bootstrap
is rejected. No rider identities are persisted. A batch interrupted before its
checkpoint can repeat work, but its reserved request allowance is not refunded.
Step Functions redrive resumes the same execution and saved allowance.

Collection stops after 24 hours, 100 batches, three batches without progress,
or exhaustion of comparable parent history. The workflow has a 26-hour overall
timeout to leave room for the final publication. `complete` means available
parent chains were checked, not that every race has an average. `limited` and
`stalled` explicitly report remaining work; races with missing parent links or
insufficient history remain visible as unknown. These terminal results still
publish the evidence collected. Unexpected errors fail the execution and alert;
the existing calendar remains available. Daily maintenance budgets are unchanged.

After deployment and a successful calendar sync, start once using the output ARN:

```sh
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli backfill-all --state-machine arn:aws:states:us-east-1:992382747916:stateMachine:zwift-calendar-history-bootstrap
uv run --frozen --directory apps/lambda/python/3.14/zwift-calendar python -m zwift_calendar.cli backfill-status
```

The start command returns an execution ARN for the AWS console/API. Status shows
both current inventory coverage and the last bootstrap report. Standard execution
history retains the final report; CloudWatch logs retain aggregate execution summaries using
a rotating customer-managed KMS key. Credentials and race target inventories
never enter workflow inputs or outputs. Infrastructure includes failure/timeout/abort
alarms, narrowly scoped invocation permissions, and no recurring bootstrap schedule.
The KMS key, alarms, and execution logs have ongoing costs even while idle; the
request allowance bounds work, not the total AWS bill. Stop an execution to halt
future batches; an in-flight Lambda may finish its current bounded batch.
