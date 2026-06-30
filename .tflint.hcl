# tflint config — used by the `tflint` CI workflow (tflint --recursive) and locally.
# Plugins are pinned; the AWS ruleset runs in static (no-API) mode so CI needs no creds.

plugin "terraform" {
  enabled = true
  preset  = "recommended"
}

# Every stack re-declares all common variables — including ones it doesn't use — so the
# shared common.tfvars never warns about undeclared vars (the "Declared (unused here)"
# convention; see CLAUDE.md). That's deliberate, so this rule would only ever false-flag.
rule "terraform_unused_declarations" {
  enabled = false
}

plugin "aws" {
  enabled = true
  version = "0.37.0"
  source  = "github.com/terraform-linters/tflint-ruleset-aws"
}
