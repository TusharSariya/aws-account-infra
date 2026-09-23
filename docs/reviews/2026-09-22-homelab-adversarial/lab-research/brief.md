# Deep research: experimental distributed-systems learning lab for a Talos homelab

Today is 2026-09-22. Use live web research against primary sources (project docs, release notes, papers, GitHub). Do not modify any files, run cluster commands, or access anything other than the web. Mark any claim you could not verify as [unverified].

## The cluster (context)
- Talos Linux Kubernetes (Talos 1.13, Kubernetes ~1.36; Talos 1.14/K8s 1.37 is current). Immutable OS: no SSH/shell, host changes only through Talos system extensions and machine config.
- 1 control plane: Talos VM (2 vCPU, 5 GiB) on an Ubuntu laptop over Wi-Fi. 2 workers: one large Talos VM each on two older dual-socket Proxmox servers (roughly 38 vCPU / 112-156 GiB RAM each, local LVM/RAID disks, one with a failed RAID cache).
- Workers physically sleep after 5 idle minutes and are woken on demand by a custom power coordinator through a Kueue AdmissionCheck. Compute namespaces must go through Kueue with explicit requests; unregistered Pods block host sleep.
- Installed: Cilium (VXLAN, kube-proxy kept), Kueue, Argo Workflows, ARC GitHub runners, CloudNativePG, Nexus, Ollama, Tailscale operator, Prometheus/Loki/Grafana, local-path storage. OpenTofu + Helm for deployment. A GPU server may be added later.

## Goal
The operator wants **experimental, fun projects purely for learning distributed systems** (consensus, replication, partitions, consistency models, clocks, failure detection, scheduling, streaming, distributed transactions, CRDTs, observability of distributed behaviour, chaos/fault injection, formal/deterministic testing, etc.). Production-readiness is NOT the goal; learning depth is. Experiments must be isolated from the production-like services (separate namespaces or an isolated virtual cluster, never touching platform data).

## Deliver
1. **A ranked shortlist of 10-15 projects** (tools, systems, or hands-on exercises). For each:
   - What distributed-systems concepts it teaches, concretely.
   - The hands-on experiment(s) to run on THIS cluster (e.g. partition a node with X and observe Y), including what to measure.
   - Talos/Kubernetes compatibility caveats (privileged needs, kernel modules/extensions, eBPF, storage), resource footprint, and interaction with the sleeping-worker/Kueue design.
   - Maturity/activity as of 2026, effort for one person, and 1-3 primary source URLs.
2. **A suggested learning path** ordering them (fundamentals first), 6-10 steps.
3. **Lab isolation setup**: how to run these safely on this cluster (e.g. vCluster/Kamaji/kind-in-pod, namespaces, Kueue queue, chaos scoping).
4. A short **"wild/frontier" section** (2026-era ideas: deterministic simulation testing, eBPF, WASM, new consensus/DB projects, etc.).
Under ~2500 words. Structured Markdown. Precision over volume.
