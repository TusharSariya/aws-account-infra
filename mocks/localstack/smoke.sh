#!/usr/bin/env bash
set -euo pipefail

ENDPOINT="${LOCALSTACK_ENDPOINT:-http://localhost:4566}"
export AWS_ACCESS_KEY_ID="${AWS_ACCESS_KEY_ID:-test}"
export AWS_SECRET_ACCESS_KEY="${AWS_SECRET_ACCESS_KEY:-test}"
export AWS_DEFAULT_REGION="${AWS_DEFAULT_REGION:-us-east-1}"

aws --endpoint-url "$ENDPOINT" sts get-caller-identity >/dev/null
aws --endpoint-url "$ENDPOINT" s3api head-bucket --bucket local-infra-sandbox
queue_url="$(aws --endpoint-url "$ENDPOINT" sqs get-queue-url --queue-name local-infra-events --query QueueUrl --output text)"
aws --endpoint-url "$ENDPOINT" sqs send-message --queue-url "$queue_url" --message-body smoke-test >/dev/null
aws --endpoint-url "$ENDPOINT" sqs purge-queue --queue-url "$queue_url"
echo "LocalStack smoke test passed."
