## Why
The homelab can now host applications, but has no private AI workspace or CPU model service. Provide reproducible infrastructure while letting the operator download and select models through the UI/API.

## What Changes
- Deploy authenticated Odysseus, internal ChromaDB/SearXNG, and a separate Ollama service on the existing worker.
- Expose workspace and model API through private Tailscale HTTPS using the existing operator.
- Build a pinned upstream Odysseus revision into private GHCR, with read-only cluster pull credentials.
- Retain application/model storage; document independent encrypted backup, restoration, model inventory and rebuild.
- Validate AVX-only CPU compatibility, then small-model and sequential Qwen3.8 27B/Gemma4 31B inference.
- Record outstanding Pi-hole client checks as deferred without claiming completion.

## Capabilities
### New Capabilities
- `odysseus-workspace`: Private authenticated workspace, model lifecycle, resource boundaries, deployment and recovery.
### Modified Capabilities
None.

## Impact
Existing Kubernetes OpenTofu root and application CI, new local Helm charts, private GHCR image build workflow, protected credentials, homelab-models PVCs and private Tailscale hostnames. No new VMs, GPU integration, public ingress or automatic model upgrades. UI-managed settings and data remain outside Terraform.
