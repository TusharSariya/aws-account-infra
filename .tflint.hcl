# tflint config — used by the `tflint` CI workflow (tflint --recursive) and locally.
# Plugins are pinned; the AWS ruleset runs in static (no-API) mode so CI needs no creds.

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# Staging deploy units share an environment variable file and intentionally declare a
# few inputs they do not consume, so this rule would false-flag that convention.
rule "terraform_unused_declarations" {
  enabled = false
}

plugin "aws" {
  enabled = true
  version = "0.37.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
