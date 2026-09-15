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
    condition     = length(proxmox_virtual_environment_vm.ci_runner) == 0 && output.capacity.memory_gib == 176
    error_message = "Foundation must not implicitly activate a runner."
  }
}

run "ci_requires_admin_key" {
  command = plan
  variables {
    vm_creation_approved = true
    ci_runner_enabled    = true
    ci_runner_ssh_public_key = ""
  }
  expect_failures = [proxmox_virtual_environment_vm.ci_runner]
}

run "ci_capacity" {
  command = plan
  variables {
    vm_creation_approved     = true
    ci_runner_enabled        = true
    ci_runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAITestFixtureOnly"
  }
  assert {
    condition     = output.capacity.vcpus == 44 && output.capacity.memory_gib == 176 && output.capacity.primary_disks_gib == 1500
    error_message = "Runner must fit the revised CPU/disk and unchanged RAM budget."
  }
  assert {
    condition     = proxmox_virtual_environment_vm.guest["talos-worker-01"].memory[0].dedicated == 156 * 1024 && proxmox_virtual_environment_vm.guest["talos-worker-01"].cpu[0].cores == 38 && proxmox_virtual_environment_vm.guest["talos-worker-01"].disk[1].size == 1200
    error_message = "Only worker RAM may change."
  }
  assert {
    condition = !proxmox_virtual_environment_vm.ci_runner[0].started && !proxmox_virtual_environment_vm.ci_runner[0].on_boot
    error_message = "Runner must stay off until worker capacity is verified."
  }
}
