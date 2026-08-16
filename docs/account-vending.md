# AWS account and repository vending

The vending platform is deliberately split into independently recoverable OpenTofu
roots. Nothing in this document closes an AWS account, retrieves a secret value, or
allows a pull-request workflow to assume an AWS role.

## Prerequisites

Before the first account is created:

1. Create and protect the management-account state backend. Organization, account,
   repository, access, and bootstrap state keys all live there.
   Apply the organization root once with an administrator to create the ongoing vending
   roles, then set its role outputs as the two GitHub environment variables below. The
   workflow can read but cannot rewrite its own role trust or inline policy. Apply changes
   to those bootstrap identities separately with management-account administrator
   credentials after reviewing the privilege boundary.
2. Create the `PlatformAdmins`, `WorkloadOperators`, and `AWSReadOnly` groups in IAM
   Identity Center.
3. Configure the `platform-prod` GitHub environment with required approval and restrict
   it to `main`.
4. Confirm the Organizations account quota has four spare positions.
5. Confirm every manifest root email is a controlled distribution address and has never
   been associated with an AWS account.
6. Install the AWS Agent Toolkit secret-safety plugin so `asm-exec` is available.
7. Create the private `service-stack-template` GitHub template repository before vending
   a service whose manifest references it.

The organization root enables IAM trusted access plus `RootCredentialsManagement` and
`RootSessions`. It also creates the OUs declared in `catalog/catalog.json`.

The plan and apply vending roles are separate GitHub environment variables:
`ACCOUNT_VENDING_PLAN_ROLE_ARN` and `ACCOUNT_VENDING_APPLY_ROLE_ARN`. Only the apply role
belongs in the approval-protected `platform-prod` environment. Both environments also
need the state bucket, lock table, region, and `MANAGEMENT_GITHUB_OIDC_PROVIDER_ARN`
non-secret variables.

## Catalog workflow

Edit a manifest under `catalog/services/`, then regenerate and validate:

```bash
python3 scripts/service-catalog.py render
python3 scripts/service-catalog.py validate
python3 -m pytest -q tests/catalog
```

Provisioned service/environment keys, account IDs, names, and root emails are immutable.
Set `lifecycle: retired` and move the account to `Suspended/Accounts`; never delete the
entry. Account closure is intentionally not automated.

## Apply order

Use distinct backend keys and run one account root per service/environment. The protected
`account-vend` workflow performs the account and bootstrap steps together, but they remain
separate states so either half can be recovered independently:

1. `live/aws/organization/organization`
2. `live/aws/organization/accounts` for `platform/shared-services`
3. `live/aws/organization/access` after recording the SharedServices account ID
4. `live/aws/organization/bootstrap` for SharedServices (performed by `account-vend apply`)
5. `live/aws/organization/security` with SharedServices as delegated security administrator
6. module distribution infrastructure and its first module release
7. CourtBooker dev account and bootstrap through one `account-vend apply`
8. CourtBooker prod account and bootstrap through one `account-vend apply`
9. `live/aws/organization/repositories`

The security root creates an organization-wide, multi-region management-event trail and
an organization external-access analyzer. GuardDuty is present behind
`enable_guardduty=false`; turn it on only after reviewing its paid usage model and setting
an explicit cost expectation.

Do not point a bootstrap root at a bucket inside the account it is bootstrapping. Its
state stays in the management-account backend for its full lifetime.

### Account-create recovery

If an account apply fails or times out:

1. Stop automatic retries.
2. Inspect the Organizations create-account status and list accounts by the manifest
   email.
3. If the account exists, initialize the exact same state key and import its ID:

   ```bash
   tofu import -var service_id=court-booker -var environment=dev \
     -var parent_ou_id=ou-example aws_organizations_account.this 123456789012_ALLOW
   ```

4. Record the ID in the manifest, regenerate `catalog.json`, review the diff, and resume.
5. If the account does not exist, investigate the terminal status before reusing the
   email. Never substitute a fresh email to make a retry pass.

## GitHub App runtime

The repository root accepts only `GITHUB_TOKEN`; it never receives the App PEM. Run it
through `asm-exec` and the token-minting wrapper:

```bash
asm-exec -- env \
  'GITHUB_APP_PEM={{resolve:secretsmanager:github/repository-vending:SecretString:pem}}' \
  python3 scripts/repository-tofu.py \
    --app-id "$GITHUB_APP_ID" \
    --installation-id "$GITHUB_APP_INSTALLATION_ID" \
    -- tofu -chdir=live/aws/organization/repositories apply
```

The secret reference is versionless so rotation does not require a code change. Do not
enable shell tracing around this command. The wrapper removes the PEM from its environment,
mints a short-lived installation token, and replaces itself with OpenTofu without printing
either credential.

For CourtBooker, create the repository with `enable_protection=false`, import and scan
the filtered history, overlay the template through a PR, then apply again with protection
enabled. New services use the template directly.

## Module releases

Publish only from the `module-publish` environment:

```bash
scripts/publish-module.sh modules/aws/vended_account_baseline \
  vended_account_baseline 1.0.0 "$MODULE_BUCKET"
```

The bucket enforces `If-None-Match: *`, version retention, and deletion denial. Consumers
must run `scripts/verify-module.sh` against every pinned key before `tofu init`.

## CourtBooker cutover

`BOOKING_ENABLED` defaults to false and Scheduler input cannot override it. Production
requires the following gates:

1. Populate the sentinel SSM parameter through the WorkloadOperator permission set.
2. Run dev and prod dry-runs.
3. Verify the DynamoDB idempotency path, Scheduler DLQ, and alarms.
4. Disable the old scheduler and observe one complete interval with no old invocation.
5. Apply `booking_enabled=true` and enable the new production schedule.
6. Require three successful schedules, then retain the disabled old stack for seven days.
7. Roll back by disabling the new schedule before re-enabling the old one.
8. Destroy the old Playwright resources through their original state only after the
   rollback window.

## Future Control Tower enrollment

The current baseline intentionally does not create AWS Config recorders or member-account
CloudTrail trails. Before adopting Control Tower, choose manual enrollment, OU registration,
or auto-enrollment. Create `AWSControlTowerExecution` only when that selected enrollment
path requires it; do not place the role in every account preemptively.
