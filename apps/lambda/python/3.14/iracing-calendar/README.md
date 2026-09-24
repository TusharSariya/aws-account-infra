# Independent iRacing calendar

Public subscription: use the `calendar_url` output of
`aws-staging-iracing-calendar`. This is not an official iRacing service.

The calendar includes limited-start Oval, Sports Car and Formula Car series,
alternating-week races, championship rounds and paved special events. It excludes
continuous interval series and qualifying-only sessions. All published future
rounds are included; completed events remain for 30 days. Starts are UTC and
calendar clients convert them to local time. Events are free, with no alarms.
Lap-based races have no guessed end time.

EventBridge Scheduler refreshes the stored feed every Tuesday at 03:00 in
`America/St_Johns`, including daylight-saving changes. GET downloads never fetch
upstream data. Corrections can take seven days to reach this feed, plus the
subscriber application's polling delay. The feed returns 503 before initialization
and supports ETag/If-None-Match, including weak tags and 304 responses.

## Sources

- https://iracinghub.com/ : discover the current module script and its imports,
  then parse the literal series array with JSON5. Downloaded JavaScript is never
  executed. Inventory size must match the HTML's advertised count.
- https://members-assets.iracing.com/public/schedulepdf/SeasonSchedule.pdf : official
  frequency, track, round date, race length, cars and eligibility override Hub data.
  Parenthesized simulated track dates/times are never treated as race starts.
- https://www.iracing.com/special-events/ : dated special events, with exclusive
  all-day end dates when start times have not been published. Explicitly TBD dates
  cannot be placed on a calendar. Dirt and off-road specials are excluded.
- https://www.iracing.com/category/news/ : discover public `This Week in iRacing`
  posts and special-event announcements. Weekly times apply only to the named week;
  they are not extrapolated across daylight-saving transitions or future rounds.
  Known weekly overrides are retained when the news index rolls forward.

Hub's By Week view exposes exact starts for many irregular series, including IMSA
alternating-week events. Other entries still say only `4/5 Timeslots Per Week`.
Those use dated placeholders until public official starts can be verified.
Series/special-event identity mappings prevent duplicate NASCAR and Britcar rounds.
A parser/HTTP/validation failure aborts publication and leaves the previous feed.
Coverage scopes distinguish individual seasons, annual championships and special-event
years, so a rolled-out season cannot cancel previously published future events.

## Storage and operations

The private versioned bucket has a single `current.json` containing events, ICS,
feed ETag, coverage, last-success timestamp and an expiring lease. Conditional S3
writes on that same object fence both lease ownership and publication. Readers
continue to see the previous complete feed during refresh. The source validator
cache is separate and inaccessible to the feed role. Old object versions expire
after 35 days; current snapshots never expire.

Hourly health invocations only read storage. They fail after eight days without a
successful refresh and log coverage and current upcoming counts. Lambda errors,
API 5xx responses, scheduler delivery failures and queued failures alert through
SNS and the existing SES mailer. Logs last 14 days. Async retry limits are bounded.

```sh
# Local fixture tests and lint; no LocalStack calls in this app's CI job.
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar pytest
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar ruff check .

# Read-only live extraction. Writes ICS and a JSON report locally; no AWS writes.
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
  python -m iracing_calendar.cli extract --output /tmp/iracing-preview.ics

# IAM-authenticated manual sync waits for Lambda's result and prints counts/coverage.
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
  uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
  python -m iracing_calendar.cli sync --function iracing-calendar-sync
```

The manual caller needs `lambda:InvokeFunction` on `iracing-calendar-sync` only.
A competing refresh returns `busy` with a nonzero CLI exit; retry after it finishes.
A crashed worker's lease expires after ten minutes. No HTTP sync route is exposed.

## Releases

`scripts/iracing-package.py` builds deterministic, content-addressed Python 3.14 /
ARM64 artifacts using `uv.lock` and verified dependency hashes. The shared calendar
module invokes the builder, stores its hash-named release and deploys it through the
OpenTofu pipeline. CI initializes the snapshot after apply. There is no private SDK
or runtime authentication to iRacing.

`modules/aws/swimming-calendar` now accepts a package builder, handlers, route,
schedule, health threshold, storage keys and memory settings. Its swimming defaults
and existing resource addresses are preserved. The new deployment unit has an
independent state key, bucket, roles, Lambdas and failure queue. SNS/SES alerting
uses the existing alert channel and explicitly identifies iRacing failures.
