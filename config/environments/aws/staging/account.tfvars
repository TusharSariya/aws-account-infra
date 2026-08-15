# Foundational inputs for the AWS staging account root only.
# Workload roots have their own files under this directory.

aws_account_id = "992382747916"
region         = "us-east-1"

# Source profile that holds credentials allowed to assume the deploy role.
# Created/owned outside this repo (your ~/.aws/config). See scripts/bootstrap-terraform-deploy-role.sh.
aws_profile = "admin"

# Dedicated execution role assumed by every stack (created by the bootstrap-role script).
terraform_deploy_role_name = "TerraformDeploy"

# GitHub repo that CI runs from — used to pin the OIDC role trust policy.
github_owner = "TusharSariyaOrg"
github_repo  = "aws-account-infra"

default_tags = {
  managed_by = "opentofu"
  repo       = "aws-account-infra"
}

# AWS Budgets monthly cost alarm.
budget_monthly_limit_usd  = "20"
budget_notification_email = "tushar.sariya77@gmail.com"

# Homelab ECR-pull identity (IAM Roles Anywhere). Public CA cert, not a secret.
# Left as a PEM so a real CA is never invented here. Example:
# homelab_ca_certificate_pem = <<-EOT
#   -----BEGIN CERTIFICATE-----
#   ...
#   -----END CERTIFICATE-----
# EOT
homelab_ca_certificate_pem = <<-EOT
  -----BEGIN CERTIFICATE-----
  MIIFMDCCAxigAwIBAgIUWz28BR8z+sOZDcAhKYXhcZxkzyYwDQYJKoZIhvcNAQEL
  BQAwHjEcMBoGA1UEAwwTaG9tZWxhYi1lY3ItcHVsbC1jYTAeFw0yNjA3MTIwMzMx
  MjNaFw0zNjA3MDkwMzMxMjNaMB4xHDAaBgNVBAMME2hvbWVsYWItZWNyLXB1bGwt
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
  n4r6quVHTvBz1b11NGjzEkTCewIDAQABo2YwZDAdBgNVHQ4EFgQU/Xb9KDuhyQX0
  Wngv47/sEUf3mDEwHwYDVR0jBBgwFoAU/Xb9KDuhyQX0Wngv47/sEUf3mDEwEgYD
  VR0TAQH/BAgwBgEB/wIBADAOBgNVHQ8BAf8EBAMCAQYwDQYJKoZIhvcNAQELBQAD
  ggIBAEsO7GTkz3WmzObbQ5baMoReqo3nNGpfHw3Lz/Oz6OKEV737Jy92paZlHrBu
  KEe+BI/3gbV/U0VNy8CqEBqVAmrNwbhcZkonANAMkhWrrv1dKIQSD5t/DynUoHGG
  UdhlS3g2IxF6izSre0T53QKsNBfvvwQvkPZ/NABzXpj+5c0Nj6ZCLqxmIm6Tn1Pe
  fkt5W5+LnaJAoiFch2kDNf2McNriyN19fyUbdfnBNaKrnuVfSK+xqPCocFK81SIX
  qJEWMiEDiQIw0RvXMT6k+dWEQ1tiyEE0JdIa7hBsZTYPBserl6LwdZjNRNAynKHD
  KMSD4lF+ddsvpW3cP0PwvIKC3oz1MHF2QY2688gCVkm4PXdJKrjwJj4Tf/UAERRs
  ZqZVGHUVVDye8FcvyoPZ49w3rTwkmvshYH6K5iCFHNyhKrXE92FLe/vlMM3+32FT
  XNzWv7LbCUjQoS8RKL9FcraXEQYPbMrNBORgZd7Ws/nsRsiOm8IBpa/rwH5Rprfq
  OXEoHW/oYmhPCPEDsiDfU+n1fEbMC/SD9iawxGQsDsABX1lS8rLA9vsW3Sq6Zyz/
  t9VUXG7EqZxay1mP0e7847Rf39EJDel9OVh2hlQuefrDNvmr0UGKR97ji31tmtFt
  fXKlJT+hxgsLJs0TrTof1N9gpCbYBO44rMP2UaRcpS3YuKXN
  -----END CERTIFICATE-----
EOT
