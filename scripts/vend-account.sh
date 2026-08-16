#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "usage: $0 <plan|apply> <service-id> <environment>" >&2
  exit 2
fi

ACTION="$1"
SERVICE_ID="$2"
ENVIRONMENT="$3"
if [[ "$ACTION" != "plan" && "$ACTION" != "apply" ]]; then
  echo "action must be plan or apply" >&2
  exit 2
fi

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CATALOG="$REPO_ROOT/catalog/catalog.json"
ORG_ROOT="$REPO_ROOT/live/aws/organization/organization"
ACCOUNT_ROOT="$REPO_ROOT/live/aws/organization/accounts"
BOOTSTRAP_ROOT="$REPO_ROOT/live/aws/organization/bootstrap"
STATE_BUCKET="${CONTROL_PLANE_STATE_BUCKET:?CONTROL_PLANE_STATE_BUCKET is required}"
LOCK_TABLE="${CONTROL_PLANE_LOCK_TABLE:?CONTROL_PLANE_LOCK_TABLE is required}"
AWS_REGION="${AWS_REGION:-us-east-1}"

python3 "$REPO_ROOT/scripts/service-catalog.py" validate

ACCOUNT_JSON="$(python3 - "$CATALOG" "$SERVICE_ID" "$ENVIRONMENT" <<'PY'
import json
import sys

catalog = json.load(open(sys.argv[1], encoding="utf-8"))
service = catalog["services"][sys.argv[2]]
account = service["accounts"][sys.argv[3]]
print(json.dumps({**account, "github_repo": service["repository"]["name"]}))
PY
)"
ROOT_EMAIL="$(jq -r .root_email <<<"$ACCOUNT_JSON")"
OU_PATH="$(jq -r .ou_path <<<"$ACCOUNT_JSON")"
ACCOUNT_REGION="$(jq -r .region <<<"$ACCOUNT_JSON")"
BUDGET_USD="$(jq -r .budget_usd <<<"$ACCOUNT_JSON")"
GITHUB_REPO="$(jq -r .github_repo <<<"$ACCOUNT_JSON")"
ACCOUNT_NAME="$(jq -r .name <<<"$ACCOUNT_JSON")"
MANIFEST_ACCOUNT_ID="$(jq -r '.account_id // ""' <<<"$ACCOUNT_JSON")"

tofu -chdir="$ORG_ROOT" init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" \
  -backend-config="key=organization/organizational-units.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$LOCK_TABLE" \
  -backend-config="encrypt=true"

if [[ "$ACTION" == "apply" ]]; then
  MANAGEMENT_OIDC_PROVIDER_ARN="${MANAGEMENT_GITHUB_OIDC_PROVIDER_ARN:?MANAGEMENT_GITHUB_OIDC_PROVIDER_ARN is required}"
  CONTROL_REPOSITORY="${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"
  tofu -chdir="$ORG_ROOT" apply -input=false -auto-approve \
    -var "aws_profile=" \
    -var "github_owner=${CONTROL_REPOSITORY%%/*}" \
    -var "github_repo=${CONTROL_REPOSITORY#*/}" \
    -var "github_oidc_provider_arn=$MANAGEMENT_OIDC_PROVIDER_ARN" \
    -var "control_plane_state_bucket=$STATE_BUCKET" \
    -var "control_plane_lock_table=$LOCK_TABLE"
fi

OU_ID="$(tofu -chdir="$ORG_ROOT" output -json ou_ids | python3 -c 'import json,sys; print(json.load(sys.stdin)[sys.argv[1]])' "$OU_PATH")"

tofu -chdir="$ACCOUNT_ROOT" init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" \
  -backend-config="key=organization/accounts/$SERVICE_ID/$ENVIRONMENT.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$LOCK_TABLE" \
  -backend-config="encrypt=true"

TOFU_ARGS=(
  -var "aws_profile="
  -var "service_id=$SERVICE_ID"
  -var "environment=$ENVIRONMENT"
  -var "parent_ou_id=$OU_ID"
)

if [[ "$ACTION" == "plan" ]]; then
  tofu -chdir="$ACCOUNT_ROOT" plan -input=false "${TOFU_ARGS[@]}"
  exit 0
fi

if ! tofu -chdir="$ACCOUNT_ROOT" state show aws_organizations_account.this >/dev/null 2>&1; then
  EXISTING_ID="$(aws organizations list-accounts --output json | python3 -c '
import json,sys
email=sys.argv[1].casefold()
matches=[a["Id"] for a in json.load(sys.stdin)["Accounts"] if a["Email"].casefold()==email]
if len(matches)>1: raise SystemExit("multiple accounts matched manifest email")
print(matches[0] if matches else "")
' "$ROOT_EMAIL")"
  if [[ -n "$EXISTING_ID" ]]; then
    tofu -chdir="$ACCOUNT_ROOT" import "${TOFU_ARGS[@]}" \
      aws_organizations_account.this "${EXISTING_ID}_ALLOW"
  elif [[ -n "$MANIFEST_ACCOUNT_ID" ]]; then
    tofu -chdir="$ACCOUNT_ROOT" import "${TOFU_ARGS[@]}" \
      aws_organizations_account.this "${MANIFEST_ACCOUNT_ID}_ALLOW"
  else
    IN_PROGRESS="$(aws organizations list-create-account-status --states IN_PROGRESS --output json | python3 -c '
import json,sys
name=sys.argv[1]
matches=[row["Id"] for row in json.load(sys.stdin)["CreateAccountStatuses"] if row["AccountName"]==name]
print(" ".join(matches))
' "$ACCOUNT_NAME")"
    if [[ -n "$IN_PROGRESS" ]]; then
      echo "account creation is already in progress for $ACCOUNT_NAME: $IN_PROGRESS" >&2
      echo "inspect the create-account status and rerun only after it reaches a terminal state" >&2
      exit 1
    fi
  fi
fi

tofu -chdir="$ACCOUNT_ROOT" apply -input=false -auto-approve "${TOFU_ARGS[@]}"
ACCOUNT_ID="$(tofu -chdir="$ACCOUNT_ROOT" output -json account | python3 -c 'import json,sys; print(json.load(sys.stdin)["account_id"])')"

APPLY_POLICY="$REPO_ROOT/catalog/policies/$SERVICE_ID.json"
if [[ ! -f "$APPLY_POLICY" ]]; then
  echo "missing service deployment policy: $APPLY_POLICY" >&2
  exit 1
fi

GITHUB_OWNER="${GITHUB_REPOSITORY_OWNER:?GITHUB_REPOSITORY_OWNER is required for account bootstrap}"
STATE_BUCKET_NAME="${ACCOUNT_ID}-${AWS_REGION}-${SERVICE_ID}-${ENVIRONMENT}-tofu-state"

tofu -chdir="$BOOTSTRAP_ROOT" init -input=false -reconfigure \
  -backend-config="bucket=$STATE_BUCKET" \
  -backend-config="key=organization/bootstrap/$SERVICE_ID/$ENVIRONMENT.tfstate" \
  -backend-config="region=$AWS_REGION" \
  -backend-config="dynamodb_table=$LOCK_TABLE" \
  -backend-config="encrypt=true"

tofu -chdir="$BOOTSTRAP_ROOT" apply -input=false -auto-approve \
  -var "account_id=$ACCOUNT_ID" \
  -var "region=$ACCOUNT_REGION" \
  -var "service_id=$SERVICE_ID" \
  -var "environment=$ENVIRONMENT" \
  -var "budget_usd=$BUDGET_USD" \
  -var "budget_emails=[\"$ROOT_EMAIL\"]" \
  -var "github_owner=$GITHUB_OWNER" \
  -var "github_repo=$GITHUB_REPO" \
  -var "state_bucket_name=$STATE_BUCKET_NAME" \
  -var "apply_policy_json=$(jq -c . "$APPLY_POLICY")"

python3 "$REPO_ROOT/scripts/service-catalog.py" record-account "$SERVICE_ID" "$ENVIRONMENT" "$ACCOUNT_ID"
echo "recorded account $SERVICE_ID/$ENVIRONMENT"
