## Context
The existing worker has 38 vCPU and 172 GiB RAM. Physical CPUs are Xeon E5-2695 v2, AVX/F16C but no AVX2/AVX512. The homelab-models namespace has an 800 GiB PVC request budget. Pi-hole already establishes Helm/OpenTofu CI and private Tailscale ingress patterns. See proposal.md for motivation.

## Goals / Non-Goals
**Goals:** UI-managed models, private workspace/API, pinned reproducible infrastructure, explicit persistence and recovery evidence.
**Non-goals:** new VMs, GPU enablement, public ingress, automatic model upgrades, automatic workspace backups, preconfigured email/calendar/cloud credentials. Open WebUI and LiteLLM are unnecessary for this first deployment.

## Decisions
- Two Helm releases in the existing Kubernetes root: ollama and odysseus (including ChromaDB/SearXNG). Single replicas/Recreate, worker placement, retained local PVCs.
- Limits: Ollama requests 8 CPU/32Gi and limits 36 CPU/64Gi, 300Gi PVC; Odysseus 1 CPU/2Gi to 4 CPU/8Gi, 20Gi PVC; Chroma 0.5 CPU/1Gi to 2 CPU/4Gi, 10Gi PVC; search 0.25 CPU/256Mi to 1 CPU/1Gi.
- CPU update: keep the worker at 38 vCPU and the workspace at its existing 4-CPU ceiling; only raise Ollama to 36 CPU (worker minus two). No VM resize/restart. This is nominal shared headroom, not CPU pinning or an exclusive reservation.
- Ollama one loaded model/one parallel inference, 4096 context, 5m keepalive. Model downloads remain runtime actions. Odysseus receives the matching Ollama CLI with OLLAMA_HOST pointing at the internal Service; no runtime/host socket is mounted.
- Build the upstream curated main revision in private GHCR, pin source archive checksum and deployed image digest. Package read credentials and workspace bootstrap password are protected prod inputs, reconciled as Kubernetes Secrets without Helm values containing secret data.
- Private HTTPS hosts odysseus.tail2f646b.ts.net and ollama.tail2f646b.ts.net reuse the operator. Authentication remains enabled for Odysseus; Ollama API relies on tailnet access. Full API access includes model management. Keep search/vector database internal.
- All workspace dependencies live in homelab-models to permit application-consistent recovery jobs to mount its PVCs. Backups quiesce workspace/vector writers, copy both volumes, restore replica counts on failure, encrypt locally before upload to existing recovery storage. No automatic scheduled outage is introduced. Recovery is not complete until isolated restore passes.
- Pin source and images; models remain UI/API-managed. Inventory names/digests permit verified re-download only while those upstream artifacts remain available. Preserve original model blobs separately if exact long-term weight recovery is required.

## Risks / Trade-offs
- Old CPU and large models: compatibility smoke test first; benchmark actual inference rather than promise speed. No vLLM requirement because this CPU lacks AVX2.
- One worker and local PVCs: host failure causes downtime; retained PVCs do not provide independent recovery.
- Shared CPU with future workloads: limits protect other services; inference remains sequential. No claim of exclusive physical cores.
- Odysseus powerful tools: workspace-only mounts, no service account token, authentication and private ingress. User-installed integrations require their own credentials.
- Private GHCR credentials: verify pull after fresh pod scheduling; document rotation and independent recovery.

## Migration Plan
Create source/image lock and build workflow; review and publish private image; deploy pinned image via approved application CI. Run endpoint and small model checks, then large downloads separately. Verify pod replacement and isolated recovery. Rollback uses prior image digest with data-compatible backup, retaining PVCs. Pi-hole remote/desktop/re-enable checks are explicitly deferred, not complete.
