provider "github" {
  owner = var.github_owner
  # Authentication is a short-lived installation token supplied only through
  # GITHUB_TOKEN. The GitHub App PEM is never passed to this provider.
}

locals {
  catalog    = jsondecode(file(var.catalog_file))
  service    = local.catalog.services[var.service_id]
  repository = local.service.repository
  templated  = local.repository.template != null && try(local.repository.migration, "template") == "template"
}

#trivy:ignore:GIT-0003 Vulnerability alerts are managed by the dedicated non-deprecated resource below.
resource "github_repository" "this" {
  # checkov:skip=CKV_GIT_3:Managed by github_repository_vulnerability_alerts below because this provider argument is deprecated.
  name                   = local.repository.name
  description            = "${local.service.service.display_name} service"
  visibility             = "private"
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

  dynamic "template" {
    for_each = local.templated ? [local.repository.template] : []
    content {
      owner                = var.github_owner
      repository           = template.value
      include_all_branches = false
    }
  }

  lifecycle {
    prevent_destroy = true
  }
}

resource "github_repository_vulnerability_alerts" "this" {
  repository = github_repository.this.name
  enabled    = true
}

resource "github_repository_environment" "dev" {
  repository  = github_repository.this.name
  environment = "dev"
}

resource "github_repository_environment" "prod" {
  repository          = github_repository.this.name
  environment         = "prod"
  prevent_self_review = true
}

resource "github_branch_protection" "main" {
  # checkov:skip=CKV_GIT_5:This personal organization has one human approver; required review, CODEOWNERS, last-push approval, and conversation resolution remain enforced.
  count = var.enable_protection ? 1 : 0

  repository_id                   = github_repository.this.node_id
  pattern                         = "main"
  enforce_admins                  = true
  allows_deletions                = false
  allows_force_pushes             = false
  require_conversation_resolution = true
  required_linear_history         = true
  require_signed_commits          = true

  required_status_checks {
    strict   = true
    contexts = local.repository.required_status_checks
  }

  required_pull_request_reviews {
    dismiss_stale_reviews           = true
    require_code_owner_reviews      = true
    require_last_push_approval      = true
    required_approving_review_count = 1
  }
}

output "repository" {
  value = {
    name      = github_repository.this.name
    full_name = github_repository.this.full_name
    html_url  = github_repository.this.html_url
  }
}
