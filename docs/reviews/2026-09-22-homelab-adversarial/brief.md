# Adversarial review brief: homelab Kubernetes platform

Repo: the repository root (READ-ONLY review. Do not edit, commit, apply, or run anything that mutates infra. Read-only `kubectl get/describe`, `talosctl get/version`, `tofu validate` are OK only if already configured; never print secrets, never read tfstate secret values, never call Secrets Manager.)

## Operator's stated topology
- 1 Kubernetes control plane: a Talos VM running on an Ubuntu laptop (single node).
- 2 Proxmox servers, each hosting one Talos VM as a Kubernetes worker; "auto scaling" (servers can sleep/wake, workers created/removed on demand).
- NOTE: CONTEXT.md describes a different topology (three Talos VMs on Proxmox + separate Ubuntu GPU worker). Reconcile docs vs code vs stated reality and call out drift.

## Operator's goal (validate against this)
A production-like homelab that can:
1. Run private apps, and accept public internet traffic safely.
2. Run AI workloads (incl. GPU) scheduled, on-demand, or persistent.
3. Handle security-sensitive, performance-sensitive, and latency-sensitive work.
4. Be modular, scalable, maintainable; add/remove heterogeneous workers (e.g. a GPU server) as needed.
5. Handle arbitrary workloads "in a production-like fashion".

## Where to look
kubernetes/ (platform/main, platform/two-worker, apps), platform/main-control-plane/, live/proxmox/{homelab,homelab-secondary}, config/environments/proxmox/, pilot/, docs/plans/*.md (esp. production-kubernetes-homelab-roadmap, talos-*, proxmox-kubernetes-worker, network-partition-resilience, kubernetes-security-hardening-2026, keda), docs/runbooks/, docs/homelab-network-inventory.md, CONTEXT.md, scripts/homelab-*, scripts/proxmox-*, .github/workflows/{kubernetes-validation,pilot-*,main-platform-validation,host-configuration}.yml, deploy-units.json, openspec/, validation/, canaries/.

## Output format (be adversarial, concrete, evidence-based)
1. Verdict per goal (1-5 above): MET / PARTIAL / NOT MET, one line why.
2. Findings ranked by severity (Critical/High/Medium/Low). Each: title, evidence (file:line or doc quote), failure scenario (concrete), fix.
3. Blockers vs nice-to-haves: what must change before calling this "production-like".
4. Things that are genuinely good (brief).
Distinguish "implemented in code" from "only planned in docs". Don't pad. Under ~1500 words.
