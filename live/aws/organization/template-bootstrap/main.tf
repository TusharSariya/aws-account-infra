provider "github" {
  owner = var.github_owner
}

#trivy:ignore:GIT-0003 Vulnerability alerts are managed by the dedicated non-deprecated resource below.
resource "github_repository" "template" {
  # checkov:skip=CKV_GIT_3:Managed by github_repository_vulnerability_alerts below because the repository argument is deprecated.
  name                   = var.repository_name
  description            = "Audited starting point for vended service repositories"
  visibility             = "private"
  is_template            = true
  archive_on_destroy     = true
  allow_auto_merge       = true
  allow_merge_commit     = false
  allow_rebase_merge     = false
  allow_squash_merge     = true
  delete_branch_on_merge = true
  has_discussions        = false
  has_issues             = true
  has_projects           = false
  has_wiki               = false
  auto_init              = false

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_vulnerability_alerts" "template" {
  repository = github_repository.template.name
  enabled    = true
}

resource "github_branch_protection" "main" {
  count = var.enable_protection ? 1 : 0

  repository_id                   = github_repository.template.node_id
  pattern                         = "main"
  enforce_admins                  = true
  allows_deletions                = false
  allows_force_pushes             = false
  require_conversation_resolution = true
  required_linear_history         = true
  require_signed_commits          = true

  required_status_checks {
    strict   = true
    contexts = ["test"]
  }

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = false
    require_last_push_approval      = true
    required_approving_review_count = 1
  }
}

output "repository" {
  value = github_repository.template.full_name
}
