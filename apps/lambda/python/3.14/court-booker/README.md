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
courts, including reservations made manually through Upace. Every subscription
sees the same events. Calendar operations never create or cancel Upace reservations.

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
uv run --directory apps/lambda/python/3.14/court-booker python -m booker subscription create owner
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

## Friend ACK window

When the bot books a court (`status == "booked"`), the booking state machine starts
`court-booker-api-ack` (execution name `ack-<reservation_id>`, so it starts at most once
per reservation). `booker.ack_workflow` emails each friend on that court's roster, plus
the owner, a personal link `…/acks/<token>` on the calendar HTTP API. Friends accept or
decline on a page served by `booker.ack_api`. Opening the link (GET) never changes
anything; only the form POST records an answer. When `ack_required` friends (default 2)
accept, the court is confirmed. The owner's link has a "keep it anyway" override. A
decline does not cancel early. A late accept after quorum sees "court is full".

The deadline is the earlier of `booked_at + ack_window_hours` (default 24) and 6 hours
before the slot. If quorum is missed by then:

- `ack_mode = "notify_only"`: everyone is told the court *would have been* cancelled.
  Nothing is cancelled.
- `ack_mode = "enforce"`: the booker Lambda cancels the reservation, but only when the
  reservation Upace currently holds for that slot has the same id as the one that was
  acknowledged. If nothing is held, or a different reservation is held, it reports
  `not_found` and cancels nothing. If cancellation fails, the owner is emailed to cancel
  manually and the `court-booker-api-ack-failed` alarm fires.

Only the SHA-256 of each token is stored (DynamoDB `court-booker-api-acks`, TTL-expired).
Tokens are never logged, and API access logs omit paths.

**Rollout.** Keep `ack_mode = "off"` in `config/environments/aws/staging/court-booker-api.tfvars`
until the steps below are done. `off` creates no ACK resources and leaves the booking
workflow unchanged.

1. SES prerequisite. While the account is in the SES sandbox, SES delivers only to
   verified addresses. Either verify every friend's address as an SES identity, or verify
   a sending domain and request SES production access. The sender is `ack_sender_email`
   (default `alert_email`) and must be a verified identity.
2. Set `ack_mode = "notify_only"`, review the plan, and apply. This creates the table,
   the two Lambdas, the ACK state machine, the `/acks/{token}` routes, and alarms.
3. Put the roster straight away. The parameter is created with the value `UNSET`, and
   invites fail until it holds valid JSON:

   ```bash
   # {"court1": [{"name": "Alex", "email": "alex@example.com"}], "court2": [...]}
   scripts/court-booker-put-roster.sh roster.json   # or: ... < roster.json
   ```

   The script validates the shape (activity to list of `{name, email}`), overwrites
   `/staging/court-booker-api/ack-roster`, and never prints names or addresses. Keep
   the roster file out of the repository.
4. Watch a few real bookings in `notify_only`. Then switch to `ack_mode = "enforce"`
   and apply.

Set `ack_mode` back to `"off"` to remove the feature. The table has deletion protection,
so disable that first if you really want to destroy it.

## Verification and rollout

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
