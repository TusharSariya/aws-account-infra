# Read-only ECR pull identity for the homelab Kubernetes nodes (IAM Roles Anywhere).
#
# The homelab cluster runs off-cloud (no EC2 instance role, no OIDC), so kubelet's
# ECR credential provider needs a way to obtain short-lived ECR auth tokens without
# a long-lived AWS access key. IAM Roles Anywhere provides exactly that:
#
#   operator CA  ──►  trust anchor (this file registers the CA cert bundle)
#        │
#        └─ issues per-node X.509 client certs (into Vault, dropped on each node)
#                              │
#   node's aws_signing_helper presents its client cert  ──►  Roles Anywhere
#                              │  (cert chains to the trust anchor)
#                              ▼
#            STS CreateSession vends TEMPORARY creds for the role below
#                              │
#                              ▼
#                     ecr:GetAuthorizationToken + repo-scoped image reads
#
# No IAM user and no static secret ever exist: the only durable material on a node
# is its client cert + private key, both issued by the operator's own CA. Rotating a
# node is "issue a new cert / revoke the old one," entirely outside this repo.
#
# CKV_AWS_273 (no IAM users) and CKV_AWS_40 (no user-attached policies) are satisfied
# structurally here — the ECR-read policy is attached to a role, not a user.

# The operator's Certificate Authority cert (PEM). This is the PUBLIC CA certificate
# whose private key signs each node's client cert; it is NOT a secret, but it is
# environment-specific, so the operator brings their own and supplies it via tfvars
# or `-var` at apply time. It is deliberately NOT committed to the repo.
variable "homelab_ca_certificate_pem" {
  type        = string
  description = "PEM of the operator's CA certificate, registered as the Roles Anywhere trust anchor bundle. Operator-supplied via tfvars/CLI; never committed."
  # Defaults to empty so the plan-only CI job (which cannot hold a CA) still runs;
  # a real, non-empty PEM MUST be supplied at apply time for the trust anchor to work.
  default = ""
}

# Trust anchor: tells Roles Anywhere which CA to trust when validating a node's
# presented client certificate.
resource "aws_rolesanywhere_trust_anchor" "ecr_pull" {
  name    = "homelab-ecr-pull"
  enabled = true

  source {
    source_type = "CERTIFICATE_BUNDLE"
    source_data {
      x509_certificate_data = var.homelab_ca_certificate_pem
    }
  }
}

# Trust policy: only the Roles Anywhere service may assume this role, and only when
# the request originates from OUR trust anchor (aws:SourceArn guard). The extra
# sts:TagSession / sts:SetSourceIdentity actions are required by Roles Anywhere so it
# can propagate certificate attributes onto the session.
data "aws_iam_policy_document" "ecr_pull_assume" {
  statement {
    sid    = "RolesAnywhereAssume"
    effect = "Allow"
    actions = [
      "sts:AssumeRole",
      "sts:TagSession",
      "sts:SetSourceIdentity",
    ]
    principals {
      type        = "Service"
      identifiers = ["rolesanywhere.amazonaws.com"]
    }
    condition {
      test     = "ArnEquals"
      variable = "aws:SourceArn"
      values   = [aws_rolesanywhere_trust_anchor.ecr_pull.arn]
    }
  }
}

resource "aws_iam_role" "ecr_pull" {
  name               = "homelab-ecr-pull"
  path               = "/homelab/"
  assume_role_policy = data.aws_iam_policy_document.ecr_pull_assume.json
}

# GetAuthorizationToken has no resource-level scoping in ECR and must be granted on
# "*"; the actual image reads below are pinned to this account's excalidraw-tf-rag/*
# repositories, which is the real boundary.
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

# ECR-read permissions attached to the ROLE (not a user) — this is what makes
# CKV_AWS_40 pass.
resource "aws_iam_role_policy" "ecr_pull" {
  name   = "ecr-pull"
  role   = aws_iam_role.ecr_pull.id
  policy = data.aws_iam_policy_document.ecr_pull.json
}

# Profile: the set of roles a Roles Anywhere session is allowed to request. The node
# passes this profile ARN (plus the trust anchor + role ARNs) to aws_signing_helper.
resource "aws_rolesanywhere_profile" "ecr_pull" {
  name      = "homelab-ecr-pull"
  enabled   = true
  role_arns = [aws_iam_role.ecr_pull.arn]
}
