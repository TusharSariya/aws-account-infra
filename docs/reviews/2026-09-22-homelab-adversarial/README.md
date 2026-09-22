# Homelab adversarial review (2026-09-22)

Four adversarial reviewers and two research agents evaluated whether the Talos homelab can
serve as a production-like platform for private apps, public traffic, scheduled, on-demand
and persistent AI workloads, security- and latency-sensitive work, and heterogeneous workers
that can be added and removed.

| Report | Agent | Angle |
|---|---|---|
| [review-codex-security.md](review-codex-security.md) | Codex `gpt-6-astra`, medium | Security and public exposure |
| [review-codex-reliability.md](review-codex-reliability.md) | Codex `gpt-6-astra`, medium | Reliability, failure modes, operations |
| [review-opus-workloads-ai.md](review-opus-workloads-ai.md) | Claude Opus 5.5 | Workload classes, GPU, performance and latency |
| [review-opus-architecture.md](review-opus-architecture.md) | Claude Opus 5.5 | Architecture, IaC, GitOps, maintainability |
| [research-platform-edge.md](research-platform-edge.md) | Claude Opus 5.5 | Ingress, control plane HA, lifecycle, storage, security, DX |
| [research-ai-gpu.md](research-ai-gpu.md) | Claude Opus 5.5 | GPU on Talos, queueing, scale-to-zero, serving, isolation |

All reviewers shared one brief ([brief.md](brief.md)) and worked read-only.

## Important caveat: the reviews ran against a stale tree

The reviewers read a local working tree 79 commits behind `main`. Every finding was then
re-checked against `main` at `000bb81`. Only findings that are still open were filed as issues.

### Already resolved on `main`

- **Homelab code outside version control:** `kubernetes/`, `platform/`, `live/proxmox/` and `pilot/` are committed.
- **No automatic wake:** #118 added the retained-worker power coordinator, which uses a Kueue admission check, wakes workers and shuts them down after 300 s idle.
- **No Kueue preemption or priority:** `charts/homelab-queue` defines preemption and a `WorkloadPriorityClass`. Pod-level PriorityClasses remain open (#130).
- **Stale `CLAUDE.md` Kubernetes and Ansible rules:** updated. `keda.md` and `proxmox-kubernetes-worker.md` are marked historical.
- **Primary Proxmox root without a backend:** now has an S3 backend and CI. The secondary root is still open (#131).
- **`CONTEXT.md` topology drift:** that file exists only in the local tree, not on `main`.

## Verdict (re-verified)

| Goal | Verdict |
|---|---|
| Private apps plus safe public traffic | Partial: private access works; no public ingress path (#124) |
| Scheduled, on-demand and persistent AI | Partial: automatic wake exists; no GPU path (#129) |
| Security-, performance- and latency-sensitive work | Not met (#125, #126, #127, #130) |
| Modular; add or remove heterogeneous workers | Partial (#129, #130, #131) |
| Arbitrary workloads, production-like | Not met: recovery, alerting and control-plane resilience (#119, #120, #121) |

## The central tension

Physical scale-to-zero conflicts with always-on production services unless the platform has
an explicit always-on tier. Today the laptop carries the single etcd, the API and CoreDNS over
Wi-Fi. The primary worker carries all durable data plus monitoring, Argo CD and Kueue-adjacent
services. Most blockers come from that: alerting stops when the primary sleeps, and a healthy
secondary can't serve primary-local data. The target is three tiers:

1. **Always on:** control plane, platform controllers, alerting, quorum tiebreaker.
2. **Protected stateful:** a wired worker with backed-up storage.
3. **Wakeable compute:** CPU and GPU workers.

Every workload maps to a tier through its declared runtime policy.

## Open findings

Tracking issue: #134.

| Priority | Issue | Finding |
|---|---|---|
| 1 | #119 | No alert delivery outside the cluster; no dead-man switch |
| 2 | #120 | etcd and application restore never rehearsed; no RPO/RTO |
| 3 | #121 | Laptop control plane: `Restart=no`, Wi-Fi, CoreDNS pinned there |
| 4 | #122 | Platform controllers and monitoring on the sleeping primary |
| 5 | #123 | GitOps model undecided: Argo CD manages no Applications |
| 6 | #124 | No public ingress path |
| 7 | #125 | Flat management network; tailnet allow-all |
| 8 | #126 | No enforced isolation between workload trust classes |
| 9 | #127 | Desktop account holds control-plane and hypervisor credentials |
| 10 | #128 | Storage durability: local-path only |
| 11 | #129 | No GPU worker path on Talos |
| 12 | #130 | Node classes, Pod PriorityClasses, kubelet reservations |
| 13 | #131 | Secondary Proxmox root: local state, no CI |
| 14 | #132 | Artifact trust chain (Action SHAs, signing, admission) |
| 15 | #133 | Talos 1.14 / Kubernetes 1.37 and Kueue v1beta2 |

## Recommended technologies (summary)

Details and sources are in the two research reports. Claims the agents could not confirm are marked [unverified] there.

- **Ingress:** Cloudflare Tunnel (2 replicas) in front of a Gateway API gateway, cert-manager DNS-01, Cloudflare Access. Use a VPS + WireGuard edge only where Cloudflare must not terminate TLS.
- **Control plane:** keep one node for now, wired, with automated etcd snapshots and restore drills. Move to 3 always-on members later, never 2. Skip Omni.
- **Sleep and wake:** the approach on `main` (a Kueue admission check plus a coordinator) matches the research recommendation. No upstream project resumes sleeping nodes.
- **GPU:** bare-metal Talos with NVIDIA extensions, the device plugin (or GPU Operator with driver and toolkit disabled) and time-slicing. Defer DRA.
- **Serving:** vLLM or Ollama, with weights as OCI image volumes (GA in Kubernetes 1.36). Defer KServe, llm-d and Dynamo.
- **Storage:** Proxmox CSI, CloudNativePG replicas + Barman plugin, NFS for shared data. Piraeus/LINSTOR only for always-on storage nodes.
- **Security:** Kyverno `ImageValidatingPolicy`, native ValidatingAdmissionPolicy / MutatingAdmissionPolicy, External Secrets Operator + SOPS/age for bootstrap, the Talos ingress firewall, Tetragon (Falco dropped gVisor).
- **Day-to-day:** talhelper, Renovate (Argo CD manager and Action SHA pinning), Headlamp.
