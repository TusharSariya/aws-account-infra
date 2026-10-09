aws_account_id = "992382747916"
region         = "us-east-1"
aws_profile    = "admin"
default_tags   = { managed_by = "opentofu", repo = "aws-account-infra" }

# Initial authenticated sync and both live calendar feeds verified.
schedule_enabled = true

# Enable after a deployed batch and enriched feed verification.
history_enabled = false
