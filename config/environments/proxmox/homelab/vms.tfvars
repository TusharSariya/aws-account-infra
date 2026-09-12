vms = {
  talos-cp-01 = {
    vm_id         = 100
    vcpus         = 2
    memory_gib    = 4
    disks_gib     = [100]
    mac_address   = "02:42:00:00:01:00"
    ipv4_address  = "10.42.0.220"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-amd64.iso"
    startup_order = 1
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
  }
  talos-worker-01 = {
    vm_id         = 102
    vcpus         = 38
    memory_gib    = 172
    disks_gib     = [100, 1200]
    mac_address   = "02:42:00:00:01:02"
    ipv4_address  = "10.42.0.222"
    iso_file_id   = "local:iso/talos-v1.13.9-qemu-gvisor-amd64.iso"
    startup_order = 2
    guest_agent   = true
    cpu_limit     = 0
    cpu_units     = 100
  }
}
