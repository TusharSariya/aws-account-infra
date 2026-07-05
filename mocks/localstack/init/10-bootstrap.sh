#!/usr/bin/env bash
set -euo pipefail

awslocal s3api create-bucket --bucket local-infra-sandbox
awslocal sqs create-queue --queue-name local-infra-events
