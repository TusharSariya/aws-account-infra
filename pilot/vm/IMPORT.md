# Import this exact pilot

**Only one copy may run at a time.** This is the original cluster and its credentials,
not a fresh-cluster template. Never start a destination while the source runs.
The export operation restarts the source; stop it gracefully again for relocation.
Cross-host operation remains unverified until a destination is available.

Requirements: x86-64 Linux, KVM, three schedulable vCPUs, 6 GiB guest RAM plus
at least 512 MiB *available* host reserve under load, QEMU with q35/virtio and virtio-balloon free-page-reporting support,
GNU tar, Python 3.12+, OpenSSL, iproute2, dnsmasq, nftables and ACL tools. Allow
32 GiB virtual disk growth plus archive/extraction space. Export verification uses
a second extracted copy; reserve at least 40 GiB free on the source. This guest
uses `-cpu host`, so destination CPU compatibility must be checked while offline.

1. Transfer the private archive and its `.sha256` over SSH. Keep directories 0700
   and files 0600. Treat every copy as full cluster administrative access. Do not
   upload to Git, public hosting or artifact services.
2. Verify `sha256sum -c pilot-<timestamp>.tar.gz.sha256`. Extract into an empty
   private directory using `umask 077; tar -xzf ...`. Inside it, run
   `sha256sum -c SHA256SUMS` and `qemu-img check` on both `.qcow2` files. Keep the included `metal-amd64.iso` with the original boot media.
   The system disk has explicit boot priority; the ISO is covered by SHA256SUMS.
3. Pause the source's four lifecycle user services, preserving both slot maintenance
   markers. Gracefully stop Talos with its existing talosconfig and wait for QEMU
   to exit. Do not restart it while the destination is active.
4. Review the network script against destination firewall policy. As root run
   `bash network-import.sh DESTINATION_USERNAME UPLINK_INTERFACE HOST_IPV4`.
   It creates `tp103br`, `tp103tap`, named `pilot_portable*` nft tables, and a
   runtime KVM ACL rule. The destination user must have a private primary group;
   the helper grants only that group KVM access until reboot.
   It preserves unrelated forwarding policy; another firewall may require explicit
   allow rules. Routing retains the existing worker/client LAN `10.0.0.0/24`.
   A different LAN needs a reviewed routing/firewall change, not just NAT.
5. Change worker, router and client routes for `10.0.2.0/24` to the new host IPv4
   (`ip route replace 10.0.2.0/24 via HOST_IPV4` on applicable Linux peers).
   Preserve `10.0.2.15`, bridge gateway `10.0.2.2`, guest MAC, both disk names,
   monitoring serial and the existing hostname. Ensure return routes and API,
   Talos and Cilium connectivity between the guest and existing workers.
6. As the destination user set `PILOT_VM_DIR` to the extracted directory and run
   `bash launch.sh`. The archive includes matching Talos v1.13.9 and kubectl v1.36 tools and
   the versioned `pilot-platform` scripts. Update their local profile paths if you
   use a different VM directory. If a kubelet-serving CSR is pending, run
   `python3 pilot-platform/vm/kubelet_tls.py` to validate and approve only the exact
   control-plane identity. This may be needed after reboot or certificate renewal. Validate
   kube-system UID `507117e6-f7ed-4307-a016-4ecc9a28b519`, control-plane and worker
   readiness, controllers, bound volumes, monitoring and Argo before enabling work.
   Update local credential file paths if kubeconfig references absolute paths;
   never change the cluster identity or regenerate its secrets.
7. Recreate localhost-only service port-forwards and SSH access. The archive includes
   the host telemetry TLS key, certificate and token in `host-monitoring-private`.
   They must be installed with the exporter on bridge `10.0.2.2` for telemetry and
   alert receipts. Certificate renewal must update both host and Kubernetes Secret.

Worker lifecycle automation, its provider credentials, user units, desired state
and pause markers remain host-specific and are **not** a transferable appliance.
Transfer/reconfigure them separately from the source before relocating the complete
pilot; never run two sets of reconcilers. The host exporter and journal forwarding
also require that host setup. Keep the secondary paused throughout.

For a failed destination trial, stop destination QEMU gracefully, remove its owned
network, restore peer routes to the source, then start the source. Remove only the
named nft tables/TAP/bridge and restore the saved forwarding value when appropriate.
Never start the old source while the destination runs.

Re-run the full capacity acceptance after import, Ubuntu reboot, desktop restoration,
or significant host load changes. Graphical startup has not been disabled.
