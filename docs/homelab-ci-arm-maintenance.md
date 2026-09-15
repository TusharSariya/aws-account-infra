# Talos ARM execution extension maintenance

Status: prepared for review; not executed. Real ARC run [34956404522](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34956404522) passed checkout and tool setup, then QEMU registration failed with `cannot mount binfmt_misc filesystem` / `no such device`.

## Exact change

Target only `talos-worker-01`, VM 102, `10.42.0.222`, Talos v1.13.9. Keep its 38 CPUs, 172-GiB RAM, `/dev/sda` system disk and retained 1200-GiB `/dev/sdb` data disk.

Add `siderolabs/binfmt-misc` to the existing `siderolabs/gvisor` and `siderolabs/qemu-guest-agent` extensions. The image factory generated schematic `3b7472aeaf4f801ab6c24b777111445a0dcbb77b2be8e36e8d712cc2f9dc3dc9` from exactly those three extensions. Pin the resulting v1.13.9 installer digest before execution; image verification is still pending.

Add the documented module configuration to the worker patch:

```yaml
machine:
  kernel:
    modules:
      - name: binfmt_misc
```

The [official extension instructions](https://github.com/siderolabs/extensions/blob/main/misc/binfmt-misc/README.md) require this module configuration. Installing an extension into an existing node requires Talos OS maintenance. Ordinary OpenTofu Talos resources keep `apply_mode = "no_reboot"`; do not change that safety boundary or automatically force a restart.

## Execution and verification

1. Verify the exact installer digest and extension list; retain the original installer and configuration privately. Update reviewed worker recovery inputs and their validator together. Keep the Talos/Kubernetes version pins unchanged.
2. Verify AI intentionally Off with no runtime Pods, empty shared queue, zero runner jobs and suspended ordinary schedules. Check the control plane, Pi-hole and retained-volume identity. Record worker boot ID and both VM boot flags.
3. Validate generated machine configuration against existing cluster secrets, keeping the install disk `/dev/sda` and wipe disabled. Review the worker-only configuration difference and retain it privately. Do not log machine credentials.
4. Use a dedicated recorded maintenance operation to apply the module configuration and replace the worker installer through Talos's graceful upgrade path. Allow one worker reboot. Do not reboot the control plane, force drain, reset a machine, or touch the data disk. Pi-hole may be temporarily unavailable while the worker reboots.
5. Require a new worker boot ID, Ready state, binfmt-misc extension/module availability, unchanged memory and retained volumes, healthy platform controllers and Pi-hole UDP/TCP. Verify Kueue/ARC recovery and no stale reservations.
6. Rerun the real ARC acceptance job: checkout, Docker, ARM tests and private networking. Complete separate packaging/upload and guarded private-deployment acceptance before switching CI_EXECUTOR. Require fresh empty plans after configuration reconciliation.

If the worker does not recover, stop and retain diagnostics. Use the previous pinned installer (`8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf`, digest `d44d70c735408a1e51d2899da72276d7f5cf3b6f071becbcb72a1d0252ea190c`) and original private configuration through the existing independent recovery path. Never reset or wipe to recover an extension failure.
