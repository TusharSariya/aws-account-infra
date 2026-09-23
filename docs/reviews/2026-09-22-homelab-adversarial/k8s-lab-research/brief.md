# Deep research: Kubernetes-specific experimental learning lab for a Talos homelab

Today is 2026-09-22. Use live web research against primary sources (Kubernetes docs, KEPs, release notes, SIG repos, project docs). Do not modify any files, run cluster commands, or access anything other than the web. Mark any claim you could not verify as [unverified].

## The cluster (context)
- Talos Linux Kubernetes (Talos 1.13, Kubernetes ~1.36; Talos 1.14/K8s 1.37 is current). Immutable OS: no SSH/shell, host changes only through Talos system extensions and machine config.
- 1 control plane: Talos VM (2 vCPU, 5 GiB) on an Ubuntu laptop over Wi-Fi. 2 workers: one large Talos VM each on two older dual-socket Proxmox servers (roughly 38 vCPU / 112-156 GiB RAM each, local LVM/RAID disks, one with a failed RAID cache).
- Workers physically sleep after 5 idle minutes and are woken on demand by a custom power coordinator through a Kueue AdmissionCheck. Compute namespaces must go through Kueue with explicit requests; unregistered Pods block host sleep.
- Installed: Cilium (VXLAN, kube-proxy kept), Kueue, Argo Workflows, ARC GitHub runners, CloudNativePG, Nexus, Ollama, Tailscale operator, Prometheus/Loki/Grafana, local-path storage. OpenTofu + Helm for deployment. A GPU server may be added later.

## Goal
The operator wants **experimental, Kubernetes-specific projects purely for learning how Kubernetes itself works and where it is heading**: control-plane internals (API server, etcd storage, watch/informers, admission, aggregation), controllers/operators, scheduler framework and plugins, kubelet/CRI/NRI, CNI/eBPF datapaths, CSI, Dynamic Resource Allocation, alpha/beta features and KEPs in 1.36-1.38, virtual/hosted control planes, multi-cluster, VMs/sandboxes on Kubernetes, WASM runtimes, etc. Production-readiness is NOT the goal. Experiments must be isolated from the production-like services.

A separate research track already covers generic distributed-systems projects (Maelstrom/Gossip Glomers, Toxiproxy, CRDTs, lab etcd + Porcupine, NATS, TLA+/FizzBee, turmoil, TigerBeetle VOPR, FoundationDB sim, Chaos Mesh, CockroachDB, Flink, KWOK + kube-scheduler-simulator, a simulated Kueue power coordinator, Hubble/Tetragon). Do not repeat those; focus on Kubernetes internals and features.

## Deliver
1. **A ranked shortlist of 12-15 projects.** For each:
   - What Kubernetes concepts/internals it teaches, concretely.
   - The hands-on experiment(s) on THIS cluster (what to build or break, what to observe/measure).
   - Talos/Kubernetes compatibility caveats (feature gates on Talos, privileged needs, extensions, eBPF, storage), footprint, and interaction with the sleeping-worker/Kueue design (unregistered Pods and DaemonSets block host sleep).
   - Maturity as of 2026, effort for one person, 1-3 primary source URLs.
2. **A suggested learning path** (6-10 steps).
3. **Isolation**: how to experiment with feature gates, alternative schedulers/CNIs/runtimes, or API-server flags without touching the real cluster (vCluster, Kamaji, kind/Talos-in-Docker, disposable Talos VMs on Proxmox, etc.).
4. A short **frontier** section (1.37/1.38-era KEPs and emerging projects).
Under ~2500 words. Structured Markdown. Precision over volume.
