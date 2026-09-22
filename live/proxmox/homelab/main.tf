locals {
  total_vcpus           = sum([for vm in var.vms : vm.vcpus]) + (var.ci_runner_enabled ? 4 : 0)
  total_memory_gib      = sum([for name, vm in var.vms : var.ci_runner_enabled && name == "talos-worker-01" ? 156 : vm.memory_gib]) + (var.ci_runner_enabled ? 16 : 0)
  total_guest_disks_gib = sum(flatten([for vm in var.vms : vm.disks_gib])) + (var.ci_runner_enabled ? 100 : 0)
}

resource "proxmox_virtual_environment_vm" "guest" {
  for_each = var.vms

  node_name           = var.node_name
  vm_id               = each.value.vm_id
  name                = each.key
  description         = "Managed homelab guest - ${each.key}"
  bios                = "ovmf"
  machine             = "q35"
  scsi_hardware       = "virtio-scsi-pci"
  hotplug             = "0"
  started             = each.value.started
  on_boot             = each.value.on_boot
  reboot              = false
  reboot_after_update = false
  boot_order          = ["scsi0", "ide2"]

  cpu {
    type       = "host"
    sockets    = 1
    cores      = each.value.vcpus
    hotplugged = 0
    limit      = each.value.cpu_limit
    units      = each.value.cpu_units
  }

  memory {
    dedicated = (var.ci_runner_enabled && each.key == "talos-worker-01" ? 156 : each.value.memory_gib) * 1024
    floating  = 0
  }

  efi_disk {
    datastore_id      = "local-lvm"
    file_format       = "raw"
    type              = "4m"
    pre_enrolled_keys = false
  }

  dynamic "disk" {
    for_each = each.value.disks_gib
    content {
      datastore_id = "local-lvm"
      interface    = "scsi${disk.key}"
      size         = disk.value
      file_format  = "raw"
      discard      = "ignore"
      iothread     = false
    }
  }

  cdrom {
    file_id   = each.value.iso_file_id
    interface = "ide2"
  }

  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = each.value.mac_address
  }

  agent {
    enabled = each.value.guest_agent
    trim    = false
    wait_for_ip {
      disabled = true
    }
  }

  startup {
    order = each.value.startup_order
  }

  operating_system {
    type = "l26"
  }

  lifecycle {
    prevent_destroy = true
    # Manual sleep/wake owns runtime power; infrastructure applies must not wake workers.
    ignore_changes = [started]

    precondition {
      condition     = var.vm_creation_approved
      error_message = "VM creation requires explicit approval after reviewing the live plan and outstanding readiness checks."
    }
    precondition {
      condition     = local.total_vcpus <= 40 && local.total_memory_gib <= 116 && local.total_guest_disks_gib <= 1620 && !var.ci_runner_enabled
      error_message = "Guest allocations exceed the approved host capacity budget."
    }
  }
}
