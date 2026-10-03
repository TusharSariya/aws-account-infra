# iRacing OAuth storage cutover to SSM

The calendar uses two Standard SecureString parameters with the AWS-managed
`alias/aws/ssm` key:

- `/staging/iracing-calendar/client`: OAuth client configuration and allowed account.
- `/staging/iracing-calendar/tokens`: rotating token pair, expiries and exchange state.

The sync role can `ssm:GetParameter` on both exact ARNs and `ssm:PutParameter`
only on the token parameter. It has no history, path-listing or Secrets Manager
permissions. The feed role has no credential access. IAM parameter permissions
are the access boundary with the default key. There is no customer-managed KMS key.
OpenTofu manages only names, IAM and runtime configuration; bootstrap and migration
write values directly, outside state. Do not introduce parameter data sources.

Every write explicitly selects `Type=SecureString`, `Tier=Standard`,
`KeyId=alias/aws/ssm`. Both serialized objects must fit 4,096 UTF-8 bytes. Exceeding
that limit stops migration or rotation; it never silently purchases Advanced tier.
SSM storage and standard-throughput interactions have no additional charge, but
KMS requests can still be billed. See [AWS pricing](https://aws.amazon.com/systems-manager/pricing/)
and [SecureString encryption](https://docs.aws.amazon.com/systems-manager/latest/userguide/secure-string-parameter-kms-encryption.html).

## Apply and migration order

The `tofu-apply` workflow runs `auth migrate` before the infrastructure apply for
the iRacing unit, using the existing CI deployment role. It requires no account
password and makes no iRacing OAuth exchange. This is the equivalent operator command:

```sh
AWS_PROFILE=admin AWS_DEFAULT_REGION=us-east-1 \
uv run --locked --directory apps/lambda/python/3.14/iracing-calendar \
python -m iracing_calendar.cli auth migrate \
  --client-parameter /staging/iracing-calendar/client \
  --token-parameter /staging/iracing-calendar/tokens \
  --legacy-client-secret /staging/iracing-calendar/client \
  --legacy-token-secret /staging/iracing-calendar/tokens \
  --bucket iracing-calendar-992382747916-us-east-1
```

1. Acquire the same S3 lease used by sync and hourly authentication. Busy leases
   stop the command and deployment; rerun after the existing invocation completes.
2. Read only current legacy values. Refuse uncertain/expired source tokens,
   different destination configuration, or an already active destination.
3. Check both object sizes before any write. Stage the token pair in SSM with
   `state=migration_pending`; normal authentication rejects this state.
4. Replace the legacy current token value with a token-free `migrated_to_ssm`
   marker. The old application rejects this state, preventing dual token use.
5. Activate and verify SSM, then record non-secret destination names in the existing
   snapshot. Preserve the feed and freshness timestamp; release the lease.
6. Only after success, OpenTofu changes IAM/environment and deploys the SSM-aware
   application. Removing the legacy resource declarations retires both Secrets
   Manager secrets and their dedicated KMS key using their configured recovery
   and deletion windows. The workflow then synchronously refreshes the calendar.

On later applies the snapshot marker and SSM status avoid contacting the retired
legacy storage. A new installation can run the SSM `auth bootstrap` command from
the application README first; bootstrap writes the same destination marker.

Do not bypass the pre-apply migration guard by directly applying this unit. Review
the plan for retirement of only the calendar's two OAuth secrets and its dedicated
OAuth KMS key. Swimming configurations keep OAuth disabled by default.

## Failure and recovery

Interrupted migrations are resumable. Before the legacy marker is written, a retry
reads the latest source token again because the old Lambda may have refreshed it.
After the marker is written, a retry accepts only the staged destination with the
matching migration ID. It never restores a historical secret/parameter version or
replays an OAuth exchange. A completed SSM migration remains complete even after
legacy resources have been deleted.

If refresh credentials are expired or an OAuth exchange has an uncertain outcome,
use local `auth bootstrap` from the SSM-aware checkout. It reuses stored client
configuration and securely prompts for the account password. Re-run the apply
workflow after bootstrap. If the failure happened before client configuration was
copied to SSM, bootstrap also prompts for the OAuth client details.

Between legacy deactivation and application deployment, old sync/auth invocations
fail closed and may trigger the existing error alarm. Subscribers continue seeing
the last good feed. A failed infrastructure apply can be retried; the migration
guard recognizes the completed destination and does not recopy stale tokens.

After cutover, rollback must keep the SSM storage implementation and environment
variables. Do not deploy a Secrets Manager-era artifact or restore old token values.
Apply a forward fix or bootstrap a fresh token pair instead. Snapshot rollback alone
must preserve `auth_storage`; it is not authorization to roll back token state.

## AWS contract references

- [PutParameter](https://docs.aws.amazon.com/systems-manager/latest/APIReference/API_PutParameter.html):
  SecureString, KeyId, Tier, overwrite and retained versions.
- [Parameter tiers](https://docs.aws.amazon.com/systems-manager/latest/userguide/parameter-store-advanced-parameters.html):
  Standard's 4 KB limit versus paid Advanced parameters.
- [Parameter permissions](https://docs.aws.amazon.com/systems-manager/latest/userguide/sysman-paramstore-access.html):
  scope access to individual parameters and avoid history/path permissions.
