# LocalStack sandbox

This mock environment is independent from live OpenTofu state. It provides S3, SQS,
STS, Secrets Manager, Lambda, and EventBridge Scheduler for local experiments. The
court-booker integration tests deploy a stubbed zip Lambda here; they never point a
live OpenTofu root at these endpoints.

```bash
./scripts/localstack.sh up
./scripts/localstack.sh smoke
./scripts/localstack.sh logs
./scripts/localstack.sh reset
./scripts/localstack.sh down
```

The AWS CLI must be installed for the smoke test. All endpoints bind to loopback and
use LocalStack's non-production `test` credentials.
