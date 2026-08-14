#!/usr/bin/env bash
# First deploy of the court-booker stack. Schedules stay DISABLED.
# 1) Apply ECR + secret + IAM (no Lambda until an image exists)
# 2) Build/push the arm64 image
# 3) Apply Lambda with schedule_enabled=false
#
# Put My Y credentials after step 1:
#   aws secretsmanager put-secret-value --secret-id staging/court-booker/my-y \
#     --secret-string '{"my_YMCA_username":"...","my_YMCA_password":"..."}'
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TAG="${1:-$(git -C "$REPO_ROOT" rev-parse --short HEAD)}"
APPLY=(apply)
if [[ "${COURT_BOOKER_AUTO_APPROVE:-}" == "1" ]]; then
  APPLY+=( -auto-approve )
fi

"$REPO_ROOT/scripts/infra.sh" aws-staging-court-booker "${APPLY[@]}"
"$REPO_ROOT/scripts/court-booker-image.sh" "$TAG"
"$REPO_ROOT/scripts/infra.sh" aws-staging-court-booker "${APPLY[@]}" \
  -var "booker_image_tag=${TAG}" \
  -var "schedule_enabled=false"

echo "Schedules are disabled. After a successful local book, set enabled: true in bookings.yaml"
echo "and re-apply with -var booker_image_tag=${TAG} -var schedule_enabled=true"
