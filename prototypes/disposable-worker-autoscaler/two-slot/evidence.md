# Two-endpoint scale-up and packing evidence

Observed September 20, 2026 local time (September 21 UTC), for [issue 109](https://github.com/TusharSariyaOrg/aws-account-infra/issues/109).

**PASS for new-work placement:** fitting work reused the existing secondary, overflow caused exactly the primary slot to create a worker, and new small Pods packed onto the busier secondary while primary was available.

## Live observations

1. `shared-first` requested 1200m CPU through the shared Kueue queue and ran on existing secondary `talos-pz8-98c`. Primary target remained zero. See [first-evidence.json](first-evidence.json).
2. A second 1200m Job could not fit alongside it. CA requested `prototype-primary` zero-to-one. The laptop authenticated through the primary forced-command key and created VM 9107 from local empty template 9108 on 10.0.0.224. It enrolled fresh node `talos-9mg-j21` at 10.0.0.11 with provider ID `proxmox://prototype-primary/9107`; the Job ran there. See [overflow-evidence.json](overflow-evidence.json). No secondary replacement or per-Job VM creation occurred.
3. Cancelled only the overflow test Job. With the 1200m first Job still running on secondary and primary Ready/schedulable, submitted two 150m Pods. Both were placed on secondary by the upstream `homelab-binpack` scheduler. See [packing-evidence.json](packing-evidence.json).
4. Removed the remaining two test Jobs after recording the result. Both prototype workers are retained for inspection. Existing marker Pod/volume on secondary remain intact; production VM ownership and routing were not transferred.

## Implementation verification

58 Python tests passed, including power preference ordering, primary/secondary disk guard separation and the existing lifecycle guards. Five Go tests passed, including two-group state isolation and rejection of mismatched endpoint/VM identities. Helm lint passed. The new scheduler initially lacked access to the authentication ConfigMap; added the existing narrowly scoped authentication-reader RoleBinding and auth-delegator binding, then verified scheduling and quiet recent logs.

Point-in-time control-plane working sets were approximately 17.8 MiB for the additional scheduler, 66.9 MiB for Kueue and 31.2 MiB for CA. Raw values are in [controller-footprint.json](controller-footprint.json). These idle pilot measurements do not establish production load budgets.

## Limits and next gate

Both physical hosts were already on. The preference publisher observed that state live; on/off/unknown ranking permutations were unit-tested. This does not prove a cold physical wake, failure recovery or automatic host power-off.

Primary is deliberately stateless-only and has no CSI credentials. The secondary retained-volume constraint remains in place. New-work bin packing is not migration of already-running workloads. Automatic CA deletion, app-permitted consolidation, the single 30-minute idle window, shutdown cancellation and production migration remain the next gates. Production guests currently block physical shutdown on both hosts.
