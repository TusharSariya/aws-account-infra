vms = {
  talos-cp-01 = {
    vm_id         = 100
    vcpus         = 2
    memory_gib    = 4
    disks_gib     = [100]
    mac_address   = "02:42:00:00:01:00"
    ipv4_address  = "10.42.0.220"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-amd64.iso"
    started       = true
    on_boot       = true
    startup_order = 1
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
  }
  talos-worker-01 = {
    vm_id         = 102
    vcpus         = 38
    memory_gib    = 172
    disks_gib     = [192, 1200]
    mac_address   = "02:42:00:00:01:02"
    ipv4_address  = "10.42.0.222"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso"
    started       = true
    on_boot       = true
    startup_order = 2
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
  }
}

# Retired CI VM: restore worker RAM to 172 GiB through guarded maintenance.
ci_runner_enabled        = false
ci_runner_started        = false
ci_runner_ssh_public_key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIB1o8n6cw3NhDQ9uCuQzUqtm/ZfcU6zGH9LVgZvUNzz8 macbook"
