# Court booker

Local CLI and AWS Lambda share `python -m booker`. Chromium talks to the published
Upace equipment calendar. My Y credentials come from repo-root `.env` locally and
from Secrets Manager in Lambda. Do not commit `.env`.

The Upace HTTP contract lives at [`specs/upace/openapi.yaml`](../../../specs/upace/openapi.yaml),
not in this image.

```bash
cd apps/ecr/court-booker
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install chromium
pytest tests --ignore=tests/integration
HEADLESS=0 python -m booker --activity court1 --date 2026-08-17 --time 05:00 --dry-run
```

Ad hoc book / cancel:

```bash
python -m booker --activity court1 --date 2026-08-17 --time 05:00
python -m booker --cancel --activity court1 --date 2026-08-17 --time 05:00
```

Weekly rules (same path as EventBridge; refuses unless today is the unlock day):

```bash
python -m booker --weekly --dry-run
```

Image push after the OpenTofu stack has created ECR (CI does this on changes
under `apps/ecr/court-booker/`; locally):

```bash
./scripts/ecr-image.sh court-booker
```

The HTTP/API booker is a separate zip Lambda (`apps/lambda/python/3.14/court-booker`).
Playwright EventBridge is DISABLED (`schedule_enabled = false`); the API zip cron is the live booker.

Put My Y credentials once (never in git). The OpenTofu stack creates the empty
secret; this copies `my_YMCA_username` / `my_YMCA_password` from repo-root `.env`:

```bash
./scripts/court-booker-put-secret.sh
```

Or paste JSON yourself:

```bash
aws secretsmanager put-secret-value --secret-id staging/court-booker/my-y \
  --secret-string '{"my_YMCA_username":"...","my_YMCA_password":"..."}'
```

Weekly rules live in `bookings.yaml`. Playwright EventBridge is parked with `schedule_enabled = false`; the API zip cron uses `api_schedule_enabled`.

Cron fires at the unlock instant (Monday 17:00 → Friday 17:00). Step Functions invokes Lambda up to **three times, 60 seconds apart**. The wait is in Step Functions, so Lambda is not billed for sleep. If the first attempt books, the later attempts never run. `already_held` on a later attempt is also success.

## Failure modes

Each failed Lambda attempt raises. Email fires only after the state machine gives up (all three attempts failed, or a terminal crash). The mail names the booking status (`full`, `closed`, Chromium crash, …) instead of dumping the CloudWatch JSON.

| Status | What happened | After 3 attempts |
| --- | --- | --- |
| `booked` | Reserve succeeded | success, stop |
| `already_held` | This account already has that court/date/time | success, stop |
| `closed` | Listing still locked, or start time missing from the dropdown (often taken) | retry, then **alarm** |
| `full` | Start time has no spots remaining | retry, then **alarm** |
| `auth_fail` | My Y email/password rejected | retry, then **alarm** |
| `membership` | Upace asked for an active membership | retry, then **alarm** |
| `unexpected_ui` | Captcha/PIN/MFA, missing Reserve, no Success dialog | retry, then **alarm** |
| `late` | Weekly invoke ran on a day that is not T-72h | retry, then **alarm** |
| exception / timeout | Playwright crash, missing secret, 90s timeout | retry, then **alarm** |

CLI still prints the status and exits `1` on those failures; it does not send email. `dry_run` and `cancel` are local-only and are not cron success paths.
