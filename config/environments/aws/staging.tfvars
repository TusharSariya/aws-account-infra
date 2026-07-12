# Shared inputs for AWS staging deploy units. The infra wrapper selects this file from
# deploy-units.json. Adjust the placeholders marked TODO before the first apply.

aws_account_id = "992382747916"
region         = "us-east-1"

# Source profile that holds credentials allowed to assume the deploy role.
# Created/owned outside this repo (your ~/.aws/config). See scripts/bootstrap-terraform-deploy-role.sh.
aws_profile = "admin"

# Dedicated execution role assumed by every stack (created by the bootstrap-role script).
terraform_deploy_role_name = "TerraformDeploy"

# GitHub repo that CI runs from — used to pin the OIDC role trust policy.
# TODO: confirm this matches the remote you create for this repo.
github_owner = "TusharSariyaOrg"
github_repo  = "aws-account-infra"

# Workload repo trusted to assume the rag stack's ECR-push OIDC role (builds
# and pushes the harvest / graph-rag-query images). Different repo from this
# infra repo's own CI identity above.
ecr_push_github_owner = "TusharSariyaOrg"
ecr_push_github_repo  = "excalidraw-tf-rag"

# Account-wide default tags merged onto every resource.
default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

# AWS Budgets monthly cost alarm (account/ stack).
# TODO: set a real notification email and your tolerance.
budget_monthly_limit_usd  = "20"
budget_notification_email = "tushar.sariya77@gmail.com"

# --- Homelab ECR-pull identity (IAM Roles Anywhere) -----------------------------
# The operator's own CA certificate (PEM), registered as the trust anchor that
# validates each node's client cert. This is a PUBLIC cert, not a secret, but it is
# environment-specific — BRING YOUR OWN CA and supply it here or via `-var`/`-var-file`
# at apply time. Left unset on purpose so a real CA is never committed. Example:
# homelab_ca_certificate_pem = <<-EOT
#   -----BEGIN CERTIFICATE-----
#   ...your homelab CA cert...
#   -----END CERTIFICATE-----
# EOT
homelab_ca_certificate_pem = <<-EOT
  -----BEGIN CERTIFICATE-----
  MIIFHTCCAwWgAwIBAgIUc7aFQN5sEzsFvviB5B5s40LkMfUwDQYJKoZIhvcNAQEL
  BQAwHjEcMBoGA1UEAwwTaG9tZWxhYi1lY3ItcHVsbC1jYTAeFw0yNjA3MTIwMjQ4
  MDlaFw0zNjA3MDkwMjQ4MDlaMB4xHDAaBgNVBAMME2hvbWVsYWItZWNyLXB1bGwt
  Y2EwggIiMA0GCSqGSIb3DQEBAQUAA4ICDwAwggIKAoICAQDh9Wgixh1FyVY59OUJ
  b2vhwqKS2DpxZKksTX85Uje+uo2TZKkH1dG1Rocs58xyiocqirwrZ+swMJsSgaoA
  u96fupi2Duob916mc2q41ELCWE1iSRSDXaCJTd44UV+BK3jGkOQ6jYz5WioaPVVo
  tFcdeXQ3X5LKPN8ovc69ogJs/8mh/7XTevFO6nvoNoy+gUsCx8IohzAdkXY0KYlx
  lncDBFtf7f1tdUI5VyeBE0qLBcbfVdIAPK20GackuTN3QUPV6atFai1Bb92jS3k/
  D4EgCpmkiqpl/FkllpH3q9cxvUpARfvpYAoWhGH4sUQj3uav1XOVA6egb5jj6E5F
  VGoG44jOZ9xqZjncvleULJBJ5MFKRMfmzSyVcuxuXYIDwQNs6l21pLBxNnaRPRhR
  X7jiYTXsSMU9bq/C4Ai3jcXKYMOA880hLMql/UA1456frOUz0UVnVeL9IYNYtVnv
  x0JJ0oI1lINjbRiNKrcjZFSji4zPrxP4QuYw7ZEC+I6gOfAr+UhvQPYqCtRsqJCa
  Ufr/VONM31i8qhCqpZGG2YnoCVS0rgkNXo7XzI7eYOhohv08eOOHoirt/hYx+hLB
  UHopQ8Do8sYKi9S+Ls3xaodMpOEypAm4ADHN6knq4+0iYCBN1DovTn8V8Ia6lJWw
  n4r6quVHTvBz1b11NGjzEkTCewIDAQABo1MwUTAdBgNVHQ4EFgQU/Xb9KDuhyQX0
  Wngv47/sEUf3mDEwHwYDVR0jBBgwFoAU/Xb9KDuhyQX0Wngv47/sEUf3mDEwDwYD
  VR0TAQH/BAUwAwEB/zANBgkqhkiG9w0BAQsFAAOCAgEAPgtuTBHljcBCsZed7bDk
  iuBRD8RDMUafycZdHY3rM9C+AVXK743WOrdbsuGpXrdb7y/1xeHcF/n6YENY4c0o
  UY/lmwKWS5vJLWfOLIUJYicez8tNEHY8cswWDiJuaqGaGnGCsbe4qaHdpnNIlGNe
  fPXr7acLNHLtNX/baopYbfiLnHOVmJJ/aY6l+GUrnCbgUJVMNFVEu2zDHnlmTICR
  Aq3kyTxKwvkfrRL9/Fy+nG3WHMqAaSC92yDCovr5s6SbWCFcGtN7eL2f+85BrM2F
  LnDgA/dBAtG5yRidi79zsqFng7J92QPcVESnfr6Q51uuUGCIHK5D3QzkEWMCGIza
  Vg1w9ZQ6RaP0IgGPpcuzI0p+wyFEpgPaKG4MibnfnNnQfOVsCeKBvMMlrtaFG1PK
  N7DyhprpoqW7b9mj14nttSyqOFQ7v8M+BLuKFuKDLIuOkvb4Ht5TgY9irlneW6oS
  +eLjOLBs9MMbBTb17YBhGWleTdudOdHMLPOXzFB2U/d98x32O665ei1I6EEIt67S
  jScs8vWfXJ0Np8/ZtpKxp5kH/8AF8slDpVfTMCJYw1006l/a3odlvXbdEmE4O0XU
  8GeCBRY0uGtNVeM36ZmFVYI5ErE5aW/AQdaq1GqSpZDhGvXr4iwv5jFTv3ps4kOy
  Tf4zdmHhFGfAx+XdO3T6BXQ=
  -----END CERTIFICATE-----
EOT
