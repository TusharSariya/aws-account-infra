provider "supabase" {}

locals {
  catalog  = jsondecode(file(var.catalog_file))
  service  = local.catalog.services[var.service_id]
  binding  = local.service.external_services.supabase
  retained = contains(["active", "suspended", "archived"], local.binding.lifecycle)
}

module "project" {
  count  = local.retained && !var.purge ? 1 : 0
  source = "../../../modules/external/supabase_project"

  organization_id   = local.binding.organization_id
  project_name      = local.binding.project_name
  region            = local.binding.region
  database_password = var.database_password
  site_url          = local.binding.auth.site_url
  redirect_urls     = local.binding.auth.redirect_urls
}

check "purge_matches_lifecycle" {
  assert {
    condition     = !var.purge || local.binding.lifecycle == "purge_requested"
    error_message = "purge=true requires lifecycle purge_requested in the committed catalog"
  }
}

check "v1_contract" {
  assert {
    condition = (
      local.binding.storage == "disabled" &&
      local.binding.backup_profile == "none" &&
      local.binding.auth.mode == "operator-only" &&
      !local.binding.auth.public_signup
    )
    error_message = "Supabase v1 permits operator-only Auth, disabled Storage, and no backup promise"
  }
}

output "project" {
  value = length(module.project) == 1 ? module.project[0].project : { purged = true }
}
