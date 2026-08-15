# Court booker API (Python 3.14 zip)

HTTP booker for Ches Penney. This directory is the zip Lambda source.
Playwright stays at `apps/ecr/court-booker/` (cron disabled). Packaging uses
`uv` and installs `upace==0.1.0` from CodeArtifact `sdk-stable`. `bookings.yaml`
is copied from the ECR app so both stacks share one schedule file.

```bash
./scripts/lambda-package.sh python/3.14/court-booker
```

Runtime is `python3.14` (arm64). boto3 comes from the Lambda runtime, not the zip.
