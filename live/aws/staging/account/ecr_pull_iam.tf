# Read-only ECR pull identity for the homelab Kubernetes nodes.
#
# The homelab cluster runs off-cloud (no OIDC, no instance role), so kubelet's
# ECR credential provider needs a long-lived IAM principal to exchange for a
# short-lived ECR auth token. This user is deliberately minimal: it can pull
# images from this account's excalidraw-tf-rag/* repositories and nothing else.
#
# The access key is NOT created here on purpose — an aws_iam_access_key resource
# would persist the secret in Terraform state (which lives in the shared S3
# backend). Instead the key is minted out-of-band (console or `aws iam
# create-access-key --user-name homelab-ecr-pull`) and stored only in Ansible
# Vault (vault_ecr_pull_access_key_id / vault_ecr_pull_secret_access_key), which
# the node role drops onto each kubelet host.

resource "aws_iam_user" "ecr_pull" {
  name = "homelab-ecr-pull"
  path = "/homelab/"
}

# GetAuthorizationToken has no resource-level scoping in ECR and must be granted
# on "*"; the actual image reads below are pinned to this account's
# excalidraw-tf-rag/* repositories, which is the real boundary.
data "aws_iam_policy_document" "ecr_pull" {
  # checkov:skip=CKV_AWS_356:ecr:GetAuthorizationToken does not support resource-level permissions and must use "*"; the layer/image read actions are repo-scoped below.
  statement {
    sid       = "EcrAuth"
    effect    = "Allow"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid    = "EcrPull"
    effect = "Allow"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:GetDownloadUrlForLayer",
      "ecr:BatchGetImage",
    ]
    resources = ["arn:aws:ecr:${var.region}:${var.aws_account_id}:repository/excalidraw-tf-rag/*"]
  }
}

resource "aws_iam_user_policy" "ecr_pull" {
  name   = "ecr-pull"
  user   = aws_iam_user.ecr_pull.name
  policy = data.aws_iam_policy_document.ecr_pull.json
}
