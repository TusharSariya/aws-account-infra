# Odysseus workspace and CPU inference

This service is defined by [the OpenSpec change](../openspec/changes/deploy-odysseus-tailnet-workspace/tasks.md).
Its implementation does not imply that live model, browser or recovery acceptance has passed.

## Deployment and access

The Kubernetes OpenTofu root publishes one approved four-container Pod for
`talos-worker-01`: Ollama, Odysseus, ChromaDB and SearxNG. The lifecycle controller
owns its runtime Deployment, defaulting to Off. See [lifecycle operations](homelab-lifecycle.md). The existing Tailscale
operator provides private HTTPS. There is no public ingress or Funnel.

| Endpoint | Purpose | Access |
| --- | --- | --- |
| `https://odysseus.tail2f646b.ts.net` | Chat, agents, documents, research and Cookbook | Tailscale plus Odysseus login |
| `https://ollama.tail2f646b.ts.net` | Native Ollama `/api` and OpenAI-compatible `/v1` | Tailscale plus independently issued model-user Bearer token |
| `http://127.0.0.1:11434` | Same-Pod workspace model backend | Instrumented workspace credential |

Model API access requires its application credential in addition to private Tailscale access.
Do not turn on Funnel. SearxNG and ChromaDB have no tailnet ingress.

From a Tailscale-connected computer, open the workspace and log in as `admin`.
The bootstrap password only seeds an empty database. Change an existing password
in the application; changing the GitHub secret does not reset it. Keep Tailscale
connected when travelling. Clients need neither access to the home router nor
Pi-hole DNS to use the workspace's MagicDNS hostname.

## Reproduce and upgrade

1. Check out the reviewed repository revision. Preserve it in the recovery receipt.
2. Run `bash scripts/odysseus-setup-wizard.sh` to configure protected `prod` inputs:
   `GHCR_READ_USER`, `GHCR_READ_TOKEN`, `ODYSSEUS_ADMIN_PASSWORD`, `SEARXNG_SECRET`.
   The existing Talos and Tailscale operator credentials are still required.
   The wizard saves a private copy outside Git at
   `~/.config/aws-account-infra/odysseus/credentials.env`. Save credentials
   independently; reissue expired registry tokens and rerun the wizard.
3. `odysseus-image` verifies the pinned upstream archive and builds only that
   source plus the explicit container packaging. The private GHCR package is
   `ghcr.io/tusharsariyaorg/homelab-odysseus`; CI checks its visibility. Pin the
   resulting immutable references and CI artifact receipts in `ai-values.yaml` and
   `ai-image-releases.json` before apply. Build Ollama first, then use its digest
   in the workspace CLI input. Issue the separate lifecycle bundle as documented
   in [lifecycle credentials](homelab-lifecycle.md).
4. Review `tofu-plan` in the PR. The existing `apply` label authorizes CI deployment
   and its existing auto-merge flow. Do not perform a separate local apply.
   Credential inputs are checked before any deployment. Secrets are reconciled
   directly into Kubernetes, never supplied as Helm values or Terraform resources.
5. Routine CI verifies intentional Off without starting AI and preserves Pi-hole
   DNS checks. The explicitly selected lifecycle maintenance gate exercises
   runtime behavior separately; browser and benchmark evidence remains distinct.

[GitHub documents classic PAT `read:packages` authentication](https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry).
The token owner needs package read access and SSO authorization where required.
The long-lived cluster pull credential is separate from CI's temporary publishing token.

[Upstream Odysseus](https://github.com/odysseus-dev/odysseus) is pinned in
`apps/containers/odysseus/source.lock.json`; source archive checksums and base image
digests are verified. The image records resolved Python packages in
`/app/build-requirements.txt`; GHCR records provenance and an SBOM. Retain deployed
image digests in GHCR. Rebuilding with the same source can resolve newer apt/pip
packages, so the immutable published image is the exact rollback artifact.
For an upgrade, update the source lock/checksum, review packaging compatibility,
build, then commit the new digest through another reviewed plan/apply.

The CPU package omits upstream's optional Real-ESRGAN GPU wheel builder and host
Docker CLI. Image upscaling, GPU engines, Docker-managed tools and remote host
administration are outside initial acceptance. Cookbook can install tools inside
its container, but code/package changes outside the persistent directories are
not durable; bake required dependencies into a reviewed image. No host filesystem,
Docker socket, Kubernetes token or host SSH credentials are mounted. Agent tools
still execute code within the workspace account; this is a personal trusted-user
service, not a hardened multi-tenant execution platform.

## Resource envelope

| Component | CPU request / limit | RAM request / limit | Retained storage |
| --- | --- | --- | --- |
| Ollama | 34 / 34 | 64 / 64 GiB | 300 GiB models |
| Odysseus | 1 / 1 | 8 / 8 GiB | 20 GiB workspace |
| ChromaDB | 0.5 / 0.5 | 4 / 4 GiB | 10 GiB vectors |
| SearxNG | 0.25 / 0.25 | 1 / 1 GiB | Reconstructed config |

The worker remains at 38 vCPUs. The aggregate Pod reserves 35.75 CPU and 77 GiB;
platform requests are separate. Insufficient resources leave the entire AI Pod
Pending. Pi-hole stays independent. Use Stop AI before a large unrelated workload.
Ollama permits one loaded model and one parallel inference request, a queue of 16,
default 4096-token context and five-minute model keep-alive. Runtime idle shutdown
requires 30 continuous verified minutes, independently of model unloading.

The existing shared XFS disk enforces project hard limits on the three retained
volumes. Declared limits permit overcommit and do not preallocate space. Administrative
PVC quotas and actual filesystem/thin-pool capacity checks are separate. Temporary
storage is bounded through kubelet eviction controls; those are not synchronous hard quotas.

The worker's Ivy Bridge Xeons have AVX but no AVX2. A successful image build on a
GitHub runner does not prove local binary compatibility. Test inference and ONNX
embedding on the real worker before declaring this hardware supported. Download
size is not model runtime RAM, and no large-model throughput is promised.

## Model lifecycle and acceptance

Model names, weights and user choices are managed through Ollama/UI APIs, not
Terraform. Deployment does not download weights or start model benchmarks.
Start AI explicitly through the authenticated lifecycle API. Odysseus's Cookbook
client uses the same-Pod authenticated gateway. External model clients must send
`Authorization: Bearer <model-user credential>` on every model API call; read the
credential from a private file or stdin, not a shell argument or checked-in config.
The explicit maintenance workflow downloads `smollm2:135m` for bounded CPU inference
and lifecycle verification. It does not replace the outstanding model benchmarks.

Check the JSON `done` field and response, not only curl's exit status: streaming
APIs can return an error inside an HTTP 200 stream. In the workspace, confirm the
small model appears, stream a chat, upload a harmless document and retrieve a
unique fact from it, and run a web search. This tests the CPU embedding path as
well as the LLM. Confirm unauthenticated clients cannot read conversations.

Next pull and benchmark **one at a time**, using the same calls with
`qwen3.8:27b`, then `gemma4:31b`. These are explicitly requested model tags; if a
tag is unavailable or unsupported by the pinned Ollama version, stop and record
the error rather than silently substitute a different model. Record returned
model digest, quantization, context, RSS/container memory, prompt and generation
token counts/durations, and tokens per second. Verify model switching unloads the
previous model with `/api/ps`. Do not download both in parallel.

Downloaded models survive pod replacement. To add or remove models, use Cookbook
or these APIs; no deployment PR is needed. The inventory contains actual names,
digests, sizes and metadata. Registry tags can move: after a restore, compare the
new digest to the saved one before calling the model equivalent. Exact long-term
recovery of weights requires archiving the model blobs separately if upstream
stops serving that digest. The application backup now includes model blobs along with workspace and vector data.
Its initial isolated restore bound is 2 GiB; larger datasets fail and require a
reviewed capacity/bound increase before the same full-volume rehearsal can run.

## Backup and recovery

Etcd backup preserves Kubernetes objects, not PVC contents. Use the reviewed
[application backup and isolated restore workflow](homelab-lifecycle.md#data-and-recovery-boundaries).
It waits for observed Off, mounts all three application volumes read-only, encrypts
the capture before it reaches runner disk, and restores into an empty isolated Pod
with no production mounts or network access. It checks every restored file hash,
permissions and SQLite integrity. An external Start or command revision change
invalidates the capture. It leaves AI off; no helper scales legacy Deployments.

The old manual replica-changing backup script and snapshot manifest are retired.
The protected CI artifact expires after 90 days. Keep a verified encrypted copy in
independent durable storage using the existing recovery procedure, and retain the
private age identity separately. A successful isolated file/database restore does
not prove browser behavior, model throughput, or complete host-loss recovery.
Configuration rollback cannot recover data erased by the one-time authorized reset.
