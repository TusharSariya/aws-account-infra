# Opt-in activation keeps foundation review deployable before worker maintenance.
variable "ci_runner_enabled" {
  type    = bool
  default = false
}

variable "ci_runner_started" {
  type        = bool
  default     = false
  description = "Start only after worker memory maintenance and effective capacity verification."
}

variable "ci_runner_ssh_public_key" {
  type        = string
  default     = ""
  description = "Administration public key only; never supply a private key."
  validation {
    condition     = var.ci_runner_ssh_public_key == "" || can(regex("^ssh-ed25519 [A-Za-z0-9+/=]+( .*)?$", var.ci_runner_ssh_public_key))
    error_message = "An OpenSSH Ed25519 public key is required."
  }
}

resource "proxmox_virtual_environment_download_file" "ci_ubuntu" {
  count              = var.ci_runner_enabled ? 1 : 0
  node_name          = var.node_name
  datastore_id       = "local"
  content_type       = "import"
  file_name          = "ci-ubuntu-24.04-20260911.qcow2"
  url                = "https://cloud-images.ubuntu.com/releases/noble/release-20260911/ubuntu-24.04-server-cloudimg-amd64.img"
  checksum           = "612b2c0cc1bc413a6cb8c38fd611794caf0f2b436c50013d8b3794db12ad7354"
  checksum_algorithm = "sha256"
}

resource "proxmox_virtual_environment_vm" "ci_runner" {
  count               = var.ci_runner_enabled ? 1 : 0
  node_name           = var.node_name
  vm_id               = 103
  name                = "ci-runner-01"
  description         = "Repository-managed disposable CI guest manager"
  bios                = "ovmf"
  machine             = "q35"
  scsi_hardware       = "virtio-scsi-pci"
  boot_order          = ["scsi0"]
  hotplug             = "0"
  started             = var.ci_runner_started
  on_boot             = var.ci_runner_started
  reboot_after_update = false
  cpu {
    type    = "host"
    cores   = 4
    sockets = 1
    limit   = 4
    units   = 50
  }
  memory {
    dedicated = 16384
    floating  = 0
  }
  efi_disk {
    datastore_id      = "local-lvm"
    type              = "4m"
    pre_enrolled_keys = false
  }
  disk {
    datastore_id = "local-lvm"
    interface    = "scsi0"
    size         = 100
    file_format  = "raw"
    import_from  = proxmox_virtual_environment_download_file.ci_ubuntu[0].id
    discard      = "ignore"
  }
  initialization {
    datastore_id = "local-lvm"
    ip_config {
      ipv4 {
        address = "dhcp"
      }
    }
    user_account {
      username = "ubuntu"
      keys     = [var.ci_runner_ssh_public_key]
    }
  }
  network_device {
    bridge      = "vmbr0"
    model       = "virtio"
    mac_address = "02:42:00:00:01:05"
  }
  agent {
    enabled = false # Ansible installs the agent after cloud-init; no bootstrap wait.
  }
  startup {
    order = 3
  }
  operating_system {
    type = "l26"
  }
  lifecycle {
    # Retirement is allowed only by scripts/ci_retirement_plan.py; normal CI rejects deletes.
    precondition {
      condition     = var.vm_creation_approved && var.ci_runner_ssh_public_key != ""
      error_message = "CI activation requires reviewed VM creation and an administrator public key."
    }
    precondition {
      condition     = local.total_memory_gib == 176 && local.total_vcpus == 44 && local.total_guest_disks_gib == 1500
      error_message = "CI activation must preserve the approved host capacity budget."
    }
  }
}
