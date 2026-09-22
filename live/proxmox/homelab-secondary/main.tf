locals {
  total_vcpus           = sum([for vm in var.vms : vm.vcpus])
  total_memory_gib      = sum([for vm in var.vms : vm.memory_gib])
  total_guest_disks_gib = sum(flatten([for vm in var.vms : vm.disks_gib]))
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
    dedicated = each.value.memory_gib * 1024
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
    wait_for_ip { disabled = true }
  }

  startup { order = each.value.startup_order }
  operating_system { type = "l26" }

  lifecycle {
    prevent_destroy = true
    # Manual sleep/wake owns runtime power; infrastructure applies must not wake workers.
    ignore_changes = [started]
    precondition {
      condition     = var.host_readiness_confirmed
      error_message = "Creation is gated: validate .225 is unused, host ECC is healthy, and recovery prerequisites are complete."
    }
    precondition {
      condition     = local.total_vcpus == 38 && local.total_memory_gib == 112 && local.total_guest_disks_gib == 320
      error_message = "Secondary allocation must leave the 16-GiB host reserve."
    }
  }
}
