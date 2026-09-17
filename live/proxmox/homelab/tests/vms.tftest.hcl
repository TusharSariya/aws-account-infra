variables {
  ci_runner_enabled = false
}

# Local plans only. Mocked provider never calls the Proxmox API.
mock_provider "proxmox" {}

run "readiness_gate" {
  command         = plan
  expect_failures = [proxmox_virtual_environment_vm.guest]
}

run "approved_vm_plan" {
  command = plan
  variables {
    vm_creation_approved = true
  }

  assert {
    condition = (
      output.capacity.vcpus == 40 && output.capacity.memory_gib == 176 &&
      output.capacity.primary_disks_gib == 1620 && output.capacity.efi_disk_count == 2
    )
    error_message = "Initial capacity must match the approved two-VM table, plus two EFI volumes."
  }
  assert {
    condition = alltrue([for vm in proxmox_virtual_environment_vm.guest :
      vm.bios == "ovmf" && vm.machine == "q35" &&
      vm.scsi_hardware == "virtio-scsi-pci" && vm.hotplug == "0" &&
      vm.cpu[0].type == "host" && vm.cpu[0].sockets == 1 &&
      vm.memory[0].floating == 0 && vm.started && vm.on_boot &&
      !vm.reboot_after_update && !vm.agent[0].trim &&
      vm.network_device[0].bridge == "vmbr0" && vm.network_device[0].model == "virtio" &&
      alltrue([for d in vm.disk : d.datastore_id == "local-lvm" && d.file_format == "raw" && d.discard == "ignore"])
    ])
    error_message = "VMs must preserve fixed memory, host CPU, no hotplug/discard and reviewed automatic-boot lifecycle settings."
  }
  assert {
    condition = (
      proxmox_virtual_environment_vm.guest["talos-cp-01"].cpu[0].cores == 2 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].cpu[0].cores == 38 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].memory[0].dedicated == 172 * 1024 &&
      proxmox_virtual_environment_vm.guest["talos-cp-01"].memory[0].dedicated == 4 * 1024
    )
    error_message = "CPU and RAM must match the approved two-VM allocation."
  }
  assert {
    condition = (
      length(proxmox_virtual_environment_vm.guest["talos-worker-01"].disk) == 2 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].disk[0].size == 320 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].disk[0].interface == "scsi0" &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].disk[1].size == 1200 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].disk[1].interface == "scsi1" &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].cdrom[0].file_id == "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso" &&
      proxmox_virtual_environment_vm.guest["talos-cp-01"].cdrom[0].file_id == "local:iso/talos-v1.13.9-qemu-amd64.iso" &&
      alltrue([for vm in proxmox_virtual_environment_vm.guest : vm.agent[0].enabled])
    )
    error_message = "Worker data disk and per-role extension ISOs must match the design."
  }
  assert {
    condition = (
      proxmox_virtual_environment_vm.guest["talos-cp-01"].startup[0].order == 1 &&
      proxmox_virtual_environment_vm.guest["talos-worker-01"].startup[0].order == 2
    )
    error_message = "Startup order must be control plane then worker."
  }
}
