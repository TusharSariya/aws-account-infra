# Collaboration

Follow the collaboration-principles skill for all implementation work.

# AWS guidance

- Prefer the AWS MCP Server for AWS interactions. If unavailable, use the AWS CLI.
- Before an AWS task, use the relevant AWS skill and verify uncertain API details against official documentation.
- Prefer infrastructure as code. Keep OpenTofu in this repository unless an explicit migration is approved.
- Apply AWS Well-Architected principles.
- Do not use em dashes in AWS resource names or descriptions.

# Secret safety

- Load the `aws-secrets-manager` skill before any live secret, credential, API key, token, or password operation.
- Never call `secretsmanager get-secret-value` or `batch-get-secret-value` and never contact the Secrets Manager Agent daemon directly.
- Resolve Secrets Manager values only at runtime with `asm-exec` and dynamic references of the form `{{resolve:secretsmanager:secret-id:SecretString:json-key}}`.
- Never print, commit, log, diff, or pass secret values in process arguments.
