# Talos ARM execution extension maintenance

Status: executed successfully on 2026-09-15; private receipt `arm-maintenance-20260915-04/receipt.json`. Real ARC run [34956404522](https://github.com/TusharSariyaOrg/aws-account-infra/actions/runs/34956404522) passed checkout and tool setup, then QEMU registration failed with `cannot mount binfmt_misc filesystem` / `no such device`.

## Exact change

Target only `talos-worker-01`, VM 102, `10.0.0.222`, Talos v1.13.9. Keep its 38 CPUs, 172-GiB RAM, `/dev/sda` system disk and retained 1200-GiB `/dev/sdb` data disk.

Add `siderolabs/binfmt-misc` to the existing `siderolabs/gvisor` and `siderolabs/qemu-guest-agent` extensions. The image factory generated schematic `3b7472aeaf4f801ab6c24b777111445a0dcbb77b2be8e36e8d712cc2f9dc3dc9` from exactly those three extensions. Verified v1.13.9 installer index digest: `sha256:e5e30232d1069b02db72e5b0e9d502cad7dc13b7af2cb3e087a244550291be10`. The amd64 manifest is `sha256:5e997eefa44ceea678ddfde92917622fc61ea3578ae899466d99a37a6b3045c5`.

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
4. Use `scripts/homelab-ci-arm-maintenance.py plan|apply --record PRIVATE --kubeconfig KUBECONFIG --talosconfig TALOSCONFIG`, the dedicated recorded maintenance operation to apply the module configuration and replace the worker installer through Talos's graceful upgrade path. Allow one worker reboot. Do not reboot the control plane, force drain, reset a machine, or touch the data disk. Pi-hole may be temporarily unavailable while the worker reboots.
5. Require a new worker boot ID, Ready state, binfmt-misc extension/module availability, unchanged memory and retained volumes, healthy platform controllers and Pi-hole UDP/TCP. Verify Kueue/ARC recovery and no stale reservations.
6. Rerun the real ARC acceptance job: checkout, Docker, ARM tests and private networking. Complete separate packaging/upload and guarded private-deployment acceptance before switching CI_EXECUTOR. Require fresh empty plans after configuration reconciliation.

If the worker does not recover, stop and retain diagnostics. Use the previous pinned installer (`8e8827b5b91420728f8415f3dc200fbf23b425ec07bf27cdc92a676367ee9edf`, digest `d44d70c735408a1e51d2899da72276d7f5cf3b6f071becbcb72a1d0252ea190c`) and original private configuration through the existing independent recovery path. Never reset or wipe to recover an extension failure.
