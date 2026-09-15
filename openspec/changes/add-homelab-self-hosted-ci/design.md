## Context
The approved plan retains GitHub and moves all execution to a dedicated VM. Live inspection on 2026-09-14 found 48 threads, 188.84 GiB RAM, two running guests and a 1795.99-GiB thin pool at 2.18% data / 0.22% metadata. Nested KVM is enabled on Proxmox. Existing worker RAM is 172 GiB; control plane RAM is 4 GiB. See proposal.md.

## Goals / Non-Goals
Preserve GitHub evidence, credential handling, dependency ordering and merge gates. Do not host a forge, introduce Kubernetes dependency for CI, or reuse job guests.

## Decisions
Use VM 103, ci-runner-01, 10.42.0.225, MAC 02:42:00:00:01:05, 4 vCPU, 16 GiB RAM and a 100-GiB disk. Confirm identity availability. Reduce worker RAM to 156 GiB during maintenance, preserving 176 GiB total guest RAM. Keep existing Talos disks and CPUs. OpenTofu owns hardware in the existing backend; Ansible owns Ubuntu 24.04 manager configuration and reproducible image inputs.

Run one nested KVM guest at a time, 4 vCPU / 14 GiB, with immutable checksum-pinned Ubuntu base and disposable qcow2 overlay. A manager service owns libvirt and a repository-scoped GitHub App credential. JIT registration credentials enter only the disposable guest. The guest cannot access manager files, libvirt, LAN management or the manager network address. Existing job-specific Tailscale enrollment provides authorized private access. The manager never executes repository job scripts. A completed/cancelled/failed guest is destroyed before another is registered. Restart destroys any surviving guest before reconciliation. Pause drains the current guest; resume replenishes one guest; status reports phase and blocking reason. Preserve bounded runner diagnostics with credentials redacted. Disk shortage, KVM failure or unsuccessful cleanup blocks new work. No hosted fallback.

All jobs retain their names and gates, routed to homelab-linux-x64. Fork jobs are rejected. ARM images use QEMU; ARM Lambda packaging and testing run inside pinned ARM Linux containers without changing deployment architecture. Local deployment followed by fresh CI plans remains supported; intermediate stack branches are never applied as rollbacks and tip results are not credited to unrelated commits.

## Risks / Trade-offs
One job at a time increases queues and nested virtualization/emulation may slow builds. Measure builds before declaring success. Physical host failure affects CI and workloads; retain Mac bootstrap and off-host reconstruction records. Privileged tests remain inside disposable guests. Worker resize can interrupt Pi-hole and requires explicit maintenance. Root-owned manager credentials and host-enforced network filtering separate registration authority from jobs.

## Migration Plan
Deliver foundation, manager, workflow PRs. Validate offline first. Bootstrap locally with guarded saved plan and existing state locking, using a narrowly scoped resize/create allowance. Create VM 103 stopped, with on-boot disabled. Keep `ci_runner_started=false` until worker shutdown/start applies the RAM reduction and effective 156-GiB memory is verified. Verify worker and DNS recovery before a separate guarded plan enables runner start/on-boot. Prove one job with exhausted hosted quota, then switch all workflow routing. Pause and return workflows to explicit hosted routing only on operator request; do not automatically spend minutes. Keep every live acceptance task unchecked until observed.
