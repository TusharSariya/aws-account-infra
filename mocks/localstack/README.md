# LocalStack sandbox

This mock environment is independent from live OpenTofu state. It provides S3, SQS,
and STS for local experiments and can be extended when a concrete test needs another
service.

```bash
./scripts/localstack.sh up
./scripts/localstack.sh smoke
./scripts/localstack.sh logs
./scripts/localstack.sh reset
./scripts/localstack.sh down
```

The AWS CLI must be installed for the smoke test. All endpoints bind to loopback and
use LocalStack's non-production `test` credentials.
