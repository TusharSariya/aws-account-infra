mock_provider "proxmox" {}

run "readiness_gate" {
  command         = plan
  expect_failures = [proxmox_virtual_environment_vm.guest]
  variables {
    node_name = "secondary-pve"
  }
}

run "secondary_worker_plan" {
  command = plan
  variables {
    node_name                = "secondary-pve"
    host_readiness_confirmed = true
  }

  assert {
    condition     = output.capacity.vcpus == 38 && output.capacity.memory_gib == 112 && output.capacity.primary_disks_gib == 320 && output.capacity.efi_disk_count == 1
    error_message = "Secondary worker must retain its 16-GiB host reserve."
  }
  assert {
    condition = (
      proxmox_virtual_environment_vm.guest["talos-worker-02"].vm_id == 103 &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].memory[0].dedicated == 112 * 1024 &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].on_boot &&
      length(proxmox_virtual_environment_vm.guest["talos-worker-02"].disk) == 1 &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].disk[0].size == 320 &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].network_device[0].mac_address == "02:42:00:00:01:03" &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].agent[0].enabled &&
      proxmox_virtual_environment_vm.guest["talos-worker-02"].memory[0].floating == 0
    )
    error_message = "Secondary worker must preserve the approved fixed-memory hardware contract."
  }
}
