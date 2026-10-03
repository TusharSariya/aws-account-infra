# Independent iRacing calendar

Subscription: `/calendars/iracing.ics` on the existing API Gateway URL. This is an
independent calendar, not an official iRacing service. GET serves the stored snapshot
and supports conditional ETag requests without contacting upstream sources.

## Coverage and timing

Authenticated iRacing Data API schedules discover all active paved irregular series:
Oval, Sports Car and Formula Car. Explicit race starts are read separately for every
round. Continuous interval racing and practice/qualifying-only schedules are excluded.
All published future rounds are included; completed events are retained for 30 days.
Starts are published race-session starts, including attached practice/qualifying,
not estimated green flags. Simulated weather timestamps never supply calendar starts.
Clients display confirmed UTC starts in local time. Timed events now occupy a
calendar block using the corresponding API `race_time_descriptors.session_minutes`.
This includes the scheduled session overhead and also provides an iRacing estimate
for lap/distance races, without inventing lap speeds or adding practice twice.
Descriptions label ends as estimated. Mixed lap/time races whose session block
includes the race time cap are explicitly labelled as maximum planned blocks;
they can finish much earlier when the lap limit is reached.

If session duration is missing, a published race time limit supplies a race-only
block, with omitted overhead disclosed. A reviewed hours-based special can use
the same fallback once an announcement confirms its start. Without either source,
the end remains unknown. Date-only placeholders retain their date ranges.
Duration corrections preserve UIDs and increment sequence, and the preview reports
`end_changes`. See `docs/iracing-duration-research.md` for source evidence and limits.

`catalogs/2026.json` records the complete 2026 official inventory, including all five
NASCAR rounds and separate Open/Fixed identity mappings. Names alone never resolve an
API race. Verified series, season, round, track, date and setup identities classify
specials on existing events without duplicating them. Paved future specials without
published API schedules remain dated all-day placeholders. The undated charity event
is omitted from ICS and reported. New or conflicting identities require catalog review.
Classifications expire with their year; an unreviewed new year fails closed.

The API confirms September 2026 Bristol at 250 laps in both NASCAR iRacing variants;
it is included as irregular racing, not “Bristol 500”. INDYCAR full-length road rounds
are classified separately from marquee specials using current-year official evidence.

Official special-event HTML uses fixture-tested selectors and date formats. Supported
announcements use explicit numbered GMT slots and a matching year. Announcement URLs
survive news-index rollover in the source cache. API/announcement exact-start conflicts,
malformed pages and ambiguous mappings abort publication. API credentials are never
sent to linked download hosts; redirects are disabled. GET retries, download sizes,
chunk pagination, caches and request budgets are bounded.

## Authentication

AWS stores client credentials and rotating tokens in separate Secrets Manager secrets
encrypted by a dedicated rotating KMS key. OpenTofu manages metadata and IAM only.
The feed role cannot read either secret. Hourly sync-role maintenance renews tokens
under the same lease used by extraction. New tokens are persisted before subsequent
network calls. An uncertain exchange leaves a durable pending marker: never restore
or retry an old single-use refresh token. Run local bootstrap to recover.

The user-requested root `.env` is Git-ignored, mode `0600`, and contains the local
credentials. The account password is never copied into AWS. Bootstrap reuses stored
client configuration and prompts without echo for missing fields and the password:

```sh
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
python -m iracing_calendar.cli auth bootstrap \
  --client-secret /staging/iracing-calendar/client \
  --token-secret /staging/iracing-calendar/tokens \
  --bucket iracing-calendar-992382747916-us-east-1
```

`auth status` takes the same secret arguments, without `--bucket`, and reports only
configuration, expiry timestamps and reauthentication requirements. The actual OAuth
client ID is the named client configured in Secrets Manager, not the UUID identifying
a secret on the issuer's screen.

Protocol: [OAuth token endpoint](https://oauth.iracing.com/oauth2/book/token_endpoint.html),
[Data API workflow](https://oauth.iracing.com/oauth2/book/data_api_workflow.html),
[token verification](https://oauth.iracing.com/oauth2/book/access_token.html).

## Preview and operations

Refresh runs every six hours. Hourly health checks alert once the snapshot exceeds
24 hours. Authentication failures use the sync Lambda alarm and existing SNS/SES
channel. Extraction failures leave the last good feed intact. A conditional S3 lease
fences atomic publication; concurrent invocations report busy. Snapshot versions and
content-addressed Lambda artifacts provide rollback; old snapshots expire after 35 days.

```sh
# Local API preview; rotates tokens under the lease and updates only source cache.
# Does not publish a new calendar. Outputs ICS plus a full JSON coverage/diff report.
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
SNAPSHOT_BUCKET=iracing-calendar-992382747916-us-east-1 \
IRACING_CLIENT_SECRET=/staging/iracing-calendar/client \
IRACING_TOKEN_SECRET=/staging/iracing-calendar/tokens \
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
python -m iracing_calendar.cli extract --output /tmp/iracing-preview.ics

# Inspect catalog identity coverage without authentication.
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
python -m iracing_calendar.cli catalog --year 2026

# Run fixture and storage tests.
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar pytest
IRACING_LOCALSTACK_ENDPOINT=http://localhost:4566 \
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar pytest
```

`catalogs/migration.json` preserves reviewed legacy round identities, and publication
persists that mapping in the snapshot. Corrections retain UIDs and increment sequence.
The preview lists additions, removals, start changes, inclusion reasons, unpublished
special schedules, undated events and source coverage. See `docs/iracing-api-cutover.md`
in the repository for the initial comparison and rollback references.

Deployment follows the existing PR `apply` label workflow: checks and OpenTofu plans,
CI apply, synchronous initialization, then merge. Authentication metadata and hourly
maintenance remain optional shared-module inputs; swimming defaults are unchanged.
