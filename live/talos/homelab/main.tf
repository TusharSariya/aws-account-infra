provider "talos" {}

variable "client_configuration" {
  type = object({
    ca_certificate     = string
    client_certificate = string
    client_key         = string
  })
  sensitive = true
  ephemeral = true
}

variable "machine_configurations" {
  type      = map(string)
  sensitive = true
  ephemeral = true
}

variable "worker_enabled" {
  type    = bool
  default = false
}

# Stable provider adoption reapplies identical configuration in no-reboot mode.
# It does not reinstall an already configured machine. No resets on destroy.
resource "talos_machine_configuration_apply" "control_plane" {
  node                           = "10.42.0.220"
  endpoint                       = "10.42.0.220"
  client_configuration_wo        = var.client_configuration
  machine_configuration_input_wo = var.machine_configurations["talos-cp-01"]
  apply_mode                     = "no_reboot"
  on_destroy                     = { reset = false, graceful = true, reboot = false }
  lifecycle { prevent_destroy = true }
}

resource "talos_machine_bootstrap" "cluster" {
  node                    = "10.42.0.220"
  endpoint                = "10.42.0.220"
  client_configuration_wo = var.client_configuration
  lifecycle { prevent_destroy = true }
}

# This cluster was bootstrapped exactly once before Terraform adoption.
# Import acknowledges that fact; CI rejects any bootstrap create action.
import {
  to = talos_machine_bootstrap.cluster
  id = "homelab-existing-20260913"
}

resource "talos_machine_configuration_apply" "worker" {
  count                          = var.worker_enabled ? 1 : 0
  node                           = "10.42.0.222"
  endpoint                       = "10.42.0.222"
  client_configuration_wo        = var.client_configuration
  machine_configuration_input_wo = var.machine_configurations["talos-worker-01"]
  apply_mode                     = "no_reboot"
  on_destroy                     = { reset = false, graceful = true, reboot = false }
  depends_on                     = [talos_machine_configuration_apply.control_plane, talos_machine_bootstrap.cluster]
  lifecycle { prevent_destroy = true }
}
