# Court booker API (Python 3.14 zip)

HTTP booker for Ches Penney. This directory is the zip Lambda source.
Playwright stays at `apps/ecr/court-booker/` (cron disabled). Packaging uses
`uv` and installs `upace==0.1.0` from CodeArtifact `sdk-stable`. `bookings.yaml`
is copied from the ECR app so both stacks share one schedule file.

```bash
./scripts/lambda-package.sh python/3.14/court-booker
```

Runtime is `python3.14` (arm64). boto3 comes from the Lambda runtime, not the zip.
Credentials are `/staging/court-booker-api/my-y` (SSM SecureString), not shared with
the Playwright Lambda.

## Shared calendar endpoints

The API deployment also runs `booker.calendar_writer.lambda_handler`,
`booker.calendar_feed.lambda_handler`, and
`booker.calendar_reconcile.lambda_handler` from the same versioned zip. The feed
serves one shared calendar for both configured courts, including reservations made
manually through Upace, on exactly two routes. Calendar operations never create or
cancel Upace reservations.

| Route | Auth | Sees | Calendar name | Private event summary |
| --- | --- | --- | --- | --- |
| `GET /calendars/public/bookings.ics` | none | public bookings only | `Court bookings` | omitted |
| `GET /calendars/private/{key}/bookings.ics` | single secret key | private events only (coaching) | `Coaching (private)` | `<title> - <court>`, e.g. `Coaching - 3-1 - Squash & Racquetball Court 1` |

The feed dispatches on the API Gateway `routeKey`; any other route returns `404`.

### Visibility

Every reservation is `public` or `private`. Visibility comes only from `bookings.yaml`:
a weekly rule with `visibility: private` (and an optional `title`) marks any booking
of that activity, weekday and start time as private. The booker and reconciliation
both classify through `BookingsConfig.visibility_for`; neither trusts the Scheduler
payload. A private rule classifies its slot even while `enabled: false`, so disabling
a rule never makes its earlier bookings public. Private is sticky in storage: a
record never drops from private back to public, and a cancellation keeps its
visibility. Records stored before visibility existed read as public. Manual Upace
bookings that match no private rule stay public.

### Public endpoint

The public URL is unauthenticated: anyone with it can read court names and booking
times (no titles, no private bookings). It is rate-limited by the API stage (5
requests per second, burst 10), and every request, public or private, can at most
claim the shared refresh lease, so upstream reconciliation runs at most once per
15 minutes regardless of traffic.

```text
https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com/calendars/public/bookings.ics
```

The deployment output `calendar_public_url` prints it.

### Private endpoint and key rotation

The private key lives in the SSM SecureString named by the feed's
`CALENDAR_PRIVATE_KEY_PARAMETER` environment variable
(`/staging/court-booker-api/calendar-private-key`, output
`calendar_private_key_parameter`). OpenTofu creates it with the placeholder `UNSET`
and ignores later value changes. The feed compares SHA-256 digests of the presented
and stored keys in constant time and fails closed: a missing variable or parameter,
the value `UNSET`, a value shorter than 32 characters, or any SSM error returns
`404` and logs a fixed message that never contains the key. A valid key is cached
per container for five minutes.

Set or rotate the key (and print the private URL once) with:

```bash
AWS_PROFILE=admin scripts/court-booker-calendar-key.sh
# or pass the API endpoint explicitly:
AWS_PROFILE=admin scripts/court-booker-calendar-key.sh https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com
```

The script refuses to run until the parameter exists (apply the API root first),
generates a random 32-byte URL-safe key, overwrites the parameter, and prints the URL
to stdout only. Store it like a password. Rotation is rerunning the script: the old
URL stops working within about five minutes, and every calendar app subscribed to
the private URL must be updated. Rotation cannot erase copies already downloaded.

Earlier releases issued per-subscription `{token}` links. That route and the
`subscription` CLI commands are gone; old links return `404`. Existing
`SUBSCRIPTIONS` items in the DynamoDB table are left in place, unused.

### Operator sync

Use an IAM-authenticated AWS profile:

```bash
export AWS_PROFILE=admin AWS_REGION=us-east-1
export CALENDAR_RECONCILE_FUNCTION=court-booker-api-calendar-reconcile

uv run --directory apps/lambda/python/3.14/court-booker python -m booker calendar sync
```

The operator needs Lambda InvokeFunction access to reconciliation. The sync command
waits for reconciliation and reports its result; it does not need Upace credentials
locally. The reconciliation role reads the existing encrypted SSM credential
parameter. Feed and writer roles cannot read that parameter; the feed role can read
only the calendar private key parameter.

A valid download returns the stored feed immediately and requests background
reconciliation if the last successful sync is at least 15 minutes old. This check
also runs for conditional requests that return `304`, on both endpoints. A shared,
expiring lease coalesces refreshes across both endpoints and all subscribers. An
abandoned lease expires after four minutes. Without a successful initial sync, the endpoint returns `503` with
`Retry-After: 60`; a successful empty sync returns valid empty ICS.

Reconciliation imports the next 180 days for configured equipment, validates the
complete response before writing, and marks missing or explicitly cancelled
reservations as cancelled. Failed authentication, network errors, and invalid or
incomplete responses preserve existing events. Cancelled records remain stored but
are omitted from ICS. Events remain visible for 30 days after their end. Conditional
versions prevent an older sync from overwriting newer booking results. UIDs remain
stable and revision timestamps/sequences change only when event details change.
Times use `America/St_Johns` and are emitted in UTC; ambiguous local timestamps at
daylight-saving transitions require an explicit upstream offset.

Outlook and Google control their own polling intervals. A feed-triggered background
sync can require another calendar poll before changes become visible. Use Outlook's
**Subscribe from web** or Google Calendar's **From URL**, rather than importing a
one-time copy. There is no scheduled reconciliation in v1.

## Verification and rollout

### Enabling a private weekly rule

Private rules must not fire under a zip that predates visibility, or their bookings
would publish as public. Roll out in two steps:

1. Merge the rule with `enabled: false` alongside the code. The API plan shows no
   schedule changes; CI builds `stable/court-booker/<sha>.zip`.
2. Pin `booker_api_zip_key` in `config/environments/aws/staging/court-booker-api.tfvars`
   to that zip, set the rule to `enabled: true`, and apply `aws-staging-court-booker-api`.
   The Playwright root reads the same file; its schedules stay DISABLED.

Then set the private key with `scripts/court-booker-calendar-key.sh`, subscribe to the
private URL, and run `calendar sync`.

```bash
uv run --directory apps/lambda/python/3.14/court-booker pytest
```

For isolated DynamoDB integration testing, start a disposable LocalStack instance
with the DynamoDB service enabled on a loopback port, then run the tests with
`CALENDAR_LOCALSTACK_ENDPOINT=http://localhost:14566`. Tests use explicit synthetic
credentials and temporary tables; do not point a live OpenTofu root at LocalStack.

Release through the existing package workflow, pin the resulting stable zip key in
the API deployment unit, and review its OpenTofu plan before applying. All four
runtime functions must use the same artifact. Booking schedules and the disabled
Playwright schedule are unchanged. Calendar publication retries independently of
booking; exhaustion reports **booking confirmed, calendar publication failed**.
An explicit sync can recover the event without repeating the booking operation.

After applying, run `calendar sync`, set the private key, and compare the private
ICS against actual reservations without making test bookings. Verify display times
in Outlook and the public URL in Google Calendar, and confirm the public feed omits
private bookings before sharing it. API access logs omit paths and keys; operational alerts distinguish publication, reconciliation,
feed, and workflow timeout failures.
