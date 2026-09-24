# Technology digest infrastructure

Deploy unit: `aws-staging-technology-digest`. Runtime lives in [TusharSariyaOrg/technology-digest](https://github.com/TusharSariyaOrg/technology-digest). Its README covers building artifacts and manual sample invocations.

The workload uses the existing AWS account, `TerraformDeploy` role, Lambda release bucket, verified SES identity and `court-booker-api-alerts` alarm channel. Its isolated backend key is `stacks/technology-digest/terraform.tfstate`.

```sh
./scripts/infra.sh aws-staging-technology-digest init
./scripts/infra.sh aws-staging-technology-digest plan
./scripts/infra.sh aws-staging-technology-digest apply
```

Release inputs live in `config/environments/aws/staging/technology-digest.tfvars`. Build in the workload repository, upload the content-addressed artifact, and update both artifact inputs. Do not replace a release object's bytes. A package is deployed only through OpenTofu.

Schedules default off. Establish baselines, inspect preview HTML/plain text, test SES delivery, and verify source health before setting `schedules_enabled = true`. The runtime README documents state recovery and ambiguous-send reconciliation. AWS tag aliases and source endpoints are configuration files packaged with the runtime; changing them requires a new artifact but no collector code change.

Resources: separate collector/digester Lambdas and least-privilege roles, conditional DynamoDB state, private versioned S3 archives, Scheduler schedules, asynchronous failure queue, SES delivery-event metrics and CloudWatch alarms. Hourly collection checks non-AWS sources only when their six-hour interval is due. Daily runs at 08:00; weekly Monday at 08:15, America/St_Johns. Log retention is 14 days and article/report retention is 90 days.
