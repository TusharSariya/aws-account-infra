variables {
  ci_runner_enabled = false
}

mock_provider "proxmox" {
  mock_resource "proxmox_virtual_environment_download_file" {
    defaults = { id = "local:import/ci-ubuntu-24.04-20260911.qcow2" }
  }
}

run "ci_disabled_by_default" {
  command = plan
  variables {
    vm_creation_approved = true
  }
  assert {
    condition     = length(proxmox_virtual_environment_vm.ci_runner) == 0 && output.capacity.memory_gib == 112
    error_message = "Foundation must not implicitly activate a runner."
  }
}

run "ci_requires_admin_key" {
  command = plan
  variables {
    vm_creation_approved     = true
    ci_runner_enabled        = true
    ci_runner_ssh_public_key = ""
  }
  expect_failures = [proxmox_virtual_environment_vm.ci_runner, proxmox_virtual_environment_vm.guest]
}

# The retired VM's historical budget is not expanded with the worker disk.
# Enabling it again requires a separate capacity review.
run "retired_ci_exceeds_historical_budget" {
  command = plan
  variables {
    vm_creation_approved     = true
    ci_runner_enabled        = true
    ci_runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly"
  }
  expect_failures = [proxmox_virtual_environment_vm.guest, proxmox_virtual_environment_vm.ci_runner]
}
