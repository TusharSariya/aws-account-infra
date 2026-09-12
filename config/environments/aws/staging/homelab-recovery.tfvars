aws_account_id             = "992382747916"
region                     = "us-east-1"
aws_profile                = "admin"
terraform_deploy_role_name = "TerraformDeploy"
default_tags               = { managed_by = "opentofu", repo = "aws-account-infra" }

# Increment when replacing a compromised/lost uploader identity.
backup_certificate_common_name = "homelab-backup-uploader-01"
