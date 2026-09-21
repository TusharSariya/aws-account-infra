# Runtime retirement and retained-volume evidence

Observed September 20, 2026 local time (September 21 UTC), for [issue 108](https://github.com/TusharSariyaOrg/aws-account-infra/issues/108).

**PASS:** the laptop runtime retired the disposable worker, a queued Job caused a fresh replacement, and the replacement read the exact original marker from the unchanged retained volume.

## Observed lifecycle

1. Created a separate 1-GiB scratch claim in `prototype-runtime-storage`, leaving the older storage proof untouched. Wrote, synced and read a marker on `talos-2cq-i7z` / VM 9105.
2. Called the restricted host retirement command while the retained disk was attached. It refused with the disk-reference guard; VM remained running. The laptop retirement command also refused a drain while the unmanaged marker Pod was still terminating. No force override was used.
3. After marker Pod deletion, retried the runtime command. It drained, waited for zero node VolumeAttachments, requested Talos shutdown, observed PVE stopped state, and destroyed only VM 9105 and its disposable OS disk. Runtime deleted the old Node and recorded desired size zero. The successful retirement took about 47 seconds, ending at 01:42:07 UTC.
4. Independently checked the owner9199 retained backend still existed with no attachment before mounting it on the replacement. This backend check occurred during replacement provisioning; [retired-evidence.json](retired-evidence.json) distinguishes it from the runtime's retirement observation.
5. Kueue demand caused replacement VM 9105 with hardware UUID `d4970c6b-3aba-4032-9628-9551ea7714f5`, replacing `9b266a41-b165-4120-b2dc-8e99d4396abe`. Both narrowly scoped CSI ACLs were recreated by the helper, without manual ACL repair on this replacement. See [replacement-access.json](replacement-access.json).
6. Fresh node `talos-pz8-98c` became ready, CSI registered, and the queued Job completed. Recreated only the marker Pod against the original PVC; it read the identical marker. Claim UID, PV UID and backend handle remained unchanged. Exactly one VolumeAttachment targeted the new node, and PVE scsi1 referenced that same backend volume. See [replacement-evidence.json](replacement-evidence.json).

## Bugs found and fixed

The initial attachment exposed missing per-VM ACLs: PVE had removed them during the previous guest deletion, so CSI reported `VM machine not found` even though VM ID and UUID were correct. Ensuring both user and privilege-separated token ACLs fixed attachment. The subsequent actual replacement exercised automatic ACL restoration and successfully attached the original volume.

Replacement also exposed DHCP arriving before the Talos maintenance API was listening. The first apply-config returned connection refused. Added a bounded read-only API readiness probe and restarted reconciliation against the existing new VM, without destroying/recreating it again. Configuration then succeeded. This run therefore includes diagnosis and a reconciliation restart; it is not an uninterrupted timing benchmark.

## Verification and limits

52 Python tests passed across power, CSI readiness, retirement guards and Talos API waiting. Four Go tests passed, including refusal of scale-up while the lifecycle lock is held. The prototype Trivy scan passed. Defensive hardware-generation binding and post-destroy inventory verification were added during this iteration; guard tests cover identity mismatch, while the live retirement above exercised the drain, detach, stop and disk-destruction path.

All three production nodes remained Ready. Existing VMs 100/102/103, the old stopped prototype 9104 and its retained volume were not part of retirement. VM 9105 is left running with the new marker Pod and attached scratch volume, plus a completed queued Job. The laptop provider is active; the one-transition reconciler completed successfully.

This proves one same-host lifecycle through an explicit runtime retirement entry point. CA deletion RPCs, automatic idle policy and physical power-off remain disabled. It does not prove crash recovery, adversarial concurrent administrative changes, cross-host volume movement, app migration, two-slot consolidation or production ownership transfer.
