# Court booker (Python 3.12 zip)

HTTP booker for Ches Penney via the generated `upace` SDK. This is a zip Lambda,
not a container. Playwright remains at `apps/ecr/court-booker/` with its
EventBridge schedules DISABLED.

The handler and bookings file are shared with the Playwright image
(`apps/ecr/court-booker/booker`, `bookings.yaml`). Packaging copies them and
installs `upace==0.1.0` from CodeArtifact `sdk-stable`.

```bash
# local: needs CodeArtifact auth and arm64
./scripts/lambda-package.sh python/3.12/court-booker

# after the OpenTofu stack has created the bucket
./scripts/infra.sh aws-staging-court-booker-api apply \
  -var booker_api_zip_key=stable/court-booker/<git-sha>.zip
```

Weekly EventBridge is on (`api_schedule_enabled = true`) once `booker_api_zip_key`
is set. Playwright's cron stays off (`schedule_enabled = false`).

Local CLI (same package, no zip):

```bash
cd apps/ecr/court-booker
aws codeartifact login --tool pip --domain aws-account-infra --domain-owner 992382747916 \
  --repository sdk-stable --region us-east-1
pip install upace==0.1.0 --extra-index-url https://pypi.org/simple
BOOKER_BROWSER=api python -m booker --activity court2 --date 2026-08-17 --time 06:00 --dry-run
```
