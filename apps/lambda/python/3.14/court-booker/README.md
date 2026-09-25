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

## Shared subscription calendar

The API deployment also runs `booker.calendar_writer.lambda_handler`,
`booker.calendar_feed.lambda_handler`, and
`booker.calendar_reconcile.lambda_handler` from the same versioned zip.
`GET /calendars/{token}/bookings.ics` serves one shared calendar for both configured
courts, including reservations made manually through Upace. Calendar operations never
create or cancel Upace reservations.

### Visibility and subscription scopes

Every reservation is `public` or `private`. Visibility comes only from `bookings.yaml`:
a weekly rule with `visibility: private` (and an optional `title`) marks any booking
of that activity, weekday and start time as private. The booker and reconciliation
both classify through `BookingsConfig.visibility_for`; neither trusts the Scheduler
payload. A private rule classifies its slot even while `enabled: false`, so disabling
a rule never makes its earlier bookings public. Private is sticky in storage: a
record never drops from private back to public, and a cancellation keeps its
visibility. Records stored before visibility existed read as public. Manual Upace
bookings that match no private rule stay public.

Each subscription has a scope:

| Scope | Sees | Calendar name | Private event summary |
| --- | --- | --- | --- |
| `public` (default) | public bookings only | `Court bookings` | omitted |
| `private` | everything | `Court bookings (private)` | `<title> - <court>`, e.g. `Coaching - 3-1 - Squash & Racquetball Court 1` |

Subscriptions created before scopes existed have no stored scope and are treated as
`public`, so existing links (including an earlier "owner" link) stop showing private
bookings. Create a new `--scope private` link for yourself and optionally revoke the
old one. Both scopes are bearer links on the same route; treat a private link with
the same care as any other secret.

Each subscription is a separate bearer link. Store it as a secret. Only its SHA-256
hash is persisted, and creation prints the URL once. Listing does not reveal the
token; replace a lost link by revoking it and creating another. Revocation stops
future downloads but cannot erase copies already downloaded by a calendar app.

Use an IAM-authenticated AWS profile for the operator CLI:

```bash
export AWS_PROFILE=admin AWS_REGION=us-east-1
export CALENDAR_TABLE=court-booker-api-calendar
export CALENDAR_RECONCILE_FUNCTION=court-booker-api-calendar-reconcile
# Set this from the deployment's calendar API endpoint output:
export CALENDAR_BASE_URL=https://YOUR_API_ID.execute-api.us-east-1.amazonaws.com

uv run --directory apps/lambda/python/3.14/court-booker python -m booker calendar sync
uv run --directory apps/lambda/python/3.14/court-booker python -m booker subscription create friend
uv run --directory apps/lambda/python/3.14/court-booker python -m booker subscription create me --scope private
uv run --directory apps/lambda/python/3.14/court-booker python -m booker subscription list
uv run --directory apps/lambda/python/3.14/court-booker python -m booker subscription revoke SUBSCRIPTION_ID
```

The operator needs DynamoDB GetItem, Query, PutItem and UpdateItem access to the
table's `SUBSCRIPTIONS` partition and Lambda InvokeFunction access to reconciliation.
The sync command waits for reconciliation and reports its result; it does not need
Upace credentials locally. The reconciliation role reads the existing encrypted
SSM credential parameter. Feed and writer roles cannot read that parameter.

A valid download returns the stored feed immediately and requests background
reconciliation if the last successful sync is at least 15 minutes old. This check
also runs for conditional requests that return `304`. A shared, expiring lease
coalesces refreshes across subscribers. An abandoned lease expires after four
minutes. Without a successful initial sync, the endpoint returns `503` with
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

Then create a private subscription, subscribe to it, and run `calendar sync`.

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

After applying, run `calendar sync`, create the owner subscription, and compare the
ICS against actual reservations without making test bookings. Verify display times
in Outlook and a second subscription in Google Calendar. Test revocation and
cancellation with synthetic fixtures before issuing friends' links. API access logs
omit paths and tokens; operational alerts distinguish publication, reconciliation,
feed, and workflow timeout failures.
