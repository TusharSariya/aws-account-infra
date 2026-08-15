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
#
# The operator's CA cert (PEM) is public, environment-specific, and supplied via
# var.homelab_ca_certificate_pem. It is deliberately not committed as a standalone file.

locals {
  # The Roles Anywhere chain is created only when a CA cert is actually supplied.
  # With the default "" (the plan-only CI job, which has no CA) this plans ZERO of
  # these resources instead of shipping a null trust anchor to AWS and failing with
  # a cryptic ValidationException at apply time. A real apply MUST pass the PEM.
  # trimspace guards a whitespace-only value.
  enable_ecr_pull = trimspace(var.homelab_ca_certificate_pem) != ""
}

# Trust anchor: tells Roles Anywhere which CA to trust when validating a node's
# presented client certificate.
resource "aws_rolesanywhere_trust_anchor" "ecr_pull" {
  count   = local.enable_ecr_pull ? 1 : 0
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
  count = local.enable_ecr_pull ? 1 : 0

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
      values   = [aws_rolesanywhere_trust_anchor.ecr_pull[0].arn]
    }
  }
}

resource "aws_iam_role" "ecr_pull" {
  count              = local.enable_ecr_pull ? 1 : 0
  name               = "homelab-ecr-pull"
  path               = "/homelab/"
  assume_role_policy = data.aws_iam_policy_document.ecr_pull_assume[0].json
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
  count  = local.enable_ecr_pull ? 1 : 0
  name   = "ecr-pull"
  role   = aws_iam_role.ecr_pull[0].id
  policy = data.aws_iam_policy_document.ecr_pull.json
}

# Profile: the set of roles a Roles Anywhere session is allowed to request. The node
# passes this profile ARN (plus the trust anchor + role ARNs) to aws_signing_helper.
resource "aws_rolesanywhere_profile" "ecr_pull" {
  count     = local.enable_ecr_pull ? 1 : 0
  name      = "homelab-ecr-pull"
  enabled   = true
  role_arns = [aws_iam_role.ecr_pull[0].arn]
}
