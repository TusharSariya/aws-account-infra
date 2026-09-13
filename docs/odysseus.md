# Odysseus workspace and CPU inference

This service is defined by [the OpenSpec change](../openspec/changes/deploy-odysseus-tailnet-workspace/tasks.md).
Its implementation does not imply that live model, browser or recovery acceptance has passed.

## Deployment and access

Two native Helm releases in `live/kubernetes/homelab` deploy four containers on
`talos-worker-01`: Ollama, Odysseus, ChromaDB and SearxNG. The existing Tailscale
operator provides private HTTPS. There is no public ingress or Funnel.

| Endpoint | Purpose | Access |
| --- | --- | --- |
| `https://odysseus.tail2f646b.ts.net` | Chat, agents, documents, research and Cookbook | Tailscale plus Odysseus login |
| `https://ollama.tail2f646b.ts.net` | Native Ollama `/api` and OpenAI-compatible `/v1` | Tailscale policy; no application API key |
| `http://ollama:11434` | Internal workspace model backend | Kubernetes service |

The current tailnet allow-all policy allows all tailnet members to reach the
model API, including model deletion. Scoped Tailscale policy remains an optional
improvement previously deferred by the operator. Do not turn on Funnel for these
services. SearxNG and ChromaDB have no tailnet ingress.

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
   resulting `@sha256:...` reference in `workspace-values.yaml` before apply.
4. Review `tofu-plan` in the PR. The existing `apply` label authorizes CI deployment
   and its existing auto-merge flow. Do not perform a separate local apply.
   Credential inputs are checked before any deployment. Secrets are reconciled
   directly into Kubernetes, never supplied as Helm values or Terraform resources.
5. CI waits for workloads and private trusted HTTPS, checks unauthenticated
   workspace API rejection, and preserves Pi-hole DNS checks. Complete the model
   and browser acceptance below after deployment.

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
| Ollama | 8 / 24 | 32 / 64 GiB | 300 GiB models |
| Odysseus | 1 / 4 | 2 / 8 GiB | 20 GiB workspace |
| ChromaDB | 0.5 / 2 | 1 / 4 GiB | 10 GiB vectors |
| SearxNG | 0.25 / 1 | 256 MiB / 1 GiB | Reconstructed config |

Ollama permits one loaded model and one parallel inference request, with a bounded
queue of 16, default 4096-token context and five-minute idle keep-alive. This does
not serialize unrelated weather services. Stop/unload the model before starting a
large weather workload. Individual API requests can override context/keep-alive;
the container memory limit remains the final boundary. Large contexts increase RAM.
The 330 GiB claim total fits the namespace's existing 800 GiB PVC budget. Local-path
claim sizes reserve Kubernetes quota but do not enforce filesystem usage quotas;
watch worker disk usage and leave free space for other services and restoration.

The worker's Ivy Bridge Xeons have AVX but no AVX2. A successful image build on a
GitHub runner does not prove local binary compatibility. Test inference and ONNX
embedding on the real worker before declaring this hardware supported. Download
size is not model runtime RAM, and no large-model throughput is promised.

## Model lifecycle and acceptance

Model names, weights and user choices are managed through Ollama/UI APIs, not
Terraform. Deployment does not download weights or start model benchmarks.
Odysseus's Cookbook Ollama client points at the internal Ollama service; select
Ollama as the provider. Use these equivalent native API calls from a connected
computer (stop on any error):

```bash
MODEL_API=https://ollama.tail2f646b.ts.net
curl --fail --show-error "$MODEL_API/api/version"
curl --fail --show-error "$MODEL_API/api/tags"
# Small first: inspect the JSON stream for an error and final success status.
curl --fail --show-error --no-buffer "$MODEL_API/api/pull" \
  -d '{"model":"qwen3:0.6b","stream":true}'
curl --fail --show-error "$MODEL_API/api/chat" \
  -d '{"model":"qwen3:0.6b","messages":[{"role":"user","content":"Reply with the word ready."}],"stream":false,"options":{"num_ctx":4096,"num_predict":32}}'
curl --fail --show-error "$MODEL_API/api/ps"
```

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

```bash
# Unload before a weather run (use the currently loaded model name).
curl --fail --show-error "$MODEL_API/api/generate" \
  -d '{"model":"qwen3.8:27b","keep_alive":0}'
# Export inventory outside Git after changing the catalog.
curl --fail --show-error "$MODEL_API/api/tags" > "$HOME/odysseus-model-inventory.json"
# Intentional deletion of only a model you no longer need:
# curl --fail --show-error -X DELETE "$MODEL_API/api/delete" -d '{"model":"qwen3:0.6b"}'
```

Downloaded models survive pod replacement. To add or remove models, use Cookbook
or these APIs; no deployment PR is needed. The inventory contains actual names,
digests, sizes and metadata. Registry tags can move: after a restore, compare the
new digest to the saved one before calling the model equivalent. Exact long-term
recovery of weights requires archiving the model blobs separately if upstream
stops serving that digest. Model blobs are excluded from the default workspace
backup to avoid repeatedly transferring hundreds of GiB.

## Backup and recovery

Etcd backup preserves Kubernetes objects, **not these PVC contents**. Workspace
backups include the SQLite databases, uploads, settings, application encryption
key, tools' persistent home directories, and ChromaDB files. Treat the complete
archive as sensitive. PVC retention protects accidental Helm removal; it is not
off-host recovery, redundancy, or protection from losing the worker's disk.

Take a backup before an upgrade and after valuable workspace changes. Scheduled
workspace backups are a follow-up; the existing daily etcd job does not capture
this service. Stop active research/agent work and avoid CI apply during capture.
The following helper deliberately pauses Odysseus and ChromaDB, waits for their
pods to terminate, mounts both volumes read-only, streams directly through age,
and restores their prior replica counts on success or failure. A forced kill or
lost administration machine cannot run a shell trap; manually restore both
Deployments to their recorded replica counts if interrupted that way.

```bash
# Export the existing trusted kubeconfig path in your own terminal first.
# This derives a PUBLIC encryption recipient; never display the private key.
RECOVERY_RECIPIENT=$(age-keygen -y "$HOME/.config/aws-account-infra/recovery/etcd-age-key.txt")
CAPTURE_DIR="$HOME/Backups/odysseus-$(date -u +%Y%m%dT%H%M%SZ)"
bash scripts/odysseus-backup.sh "$RECOVERY_RECIPIENT" "$CAPTURE_DIR"
```

Verify the helper exited successfully and both services recovered. Upload only
`workspace.tar.gz.age` using the existing administrator recovery access and the
[manual encrypted backup procedure](../live/aws/staging/workloads/homelab-recovery/MANUAL-BACKUP.md).
Use a unique `bootstrap/odysseus/<timestamp>/workspace.tar.gz.age` object key in
`homelab-recovery-992382747916-us-east-1`. This prefix is durable; it does **not**
currently implement rolling 30-day cleanup. Never put the only workspace recovery
copy under an expiring prefix. Automated retention that preserves the latest good
workspace backup is deferred with its scheduler.

Record the exact object version ID, encrypted SHA-256, capture time and Git/image
revision in an independently saved receipt. Download the exact version, compare
the encrypted checksum, and perform the isolated restore below. An upload alone
is not restore validation. Do not delete an older known-good backup before the
replacement has been restored successfully.

## Isolated restore rehearsal

Use a fresh namespace and fresh claims; never extract over live volumes. This
rehearsal has no Tailscale ingress, no Ollama deployment, and a NetworkPolicy that
permits only same-namespace communication and DNS. That blocks restored scheduled
work/integrations from contacting production or Internet destinations. Access the
UI only through local `kubectl port-forward` and do not enable restored schedules.
Ensure free worker disk capacity first. The helper commands below require Helm,
Python with PyYAML (via uv), kubectl and age. Use the saved repository revision.

```bash
kubectl create namespace odysseus-restore
kubectl apply -f config/environments/kubernetes/homelab/recovery/isolation.yaml
helm template odysseus charts/homelab-odysseus -n odysseus-restore \
  -f config/environments/kubernetes/homelab/workspace-values.yaml \
  --set replicas=0 --set ingressEnabled=false | kubectl -n odysseus-restore apply -f -
# Copy required Secrets directly between namespaces, without printing their data.
for name in ghcr-read odysseus-bootstrap; do
  kubectl -n homelab-models get secret "$name" -o json |
    python3 -c 'import sys,json; d=json.load(sys.stdin); d["metadata"]={"name":d["metadata"]["name"],"namespace":"odysseus-restore"}; print(json.dumps(d))' |
    kubectl -n odysseus-restore create -f -
done
# Reuse the bounded helper with writable mounts on the NEW namespace's claims.
uv run --with PyYAML==6.0.3 python -c '
import yaml,json
p=yaml.safe_load(open("config/environments/kubernetes/homelab/recovery/snapshot-pod.yaml"))
p["metadata"]["namespace"]="odysseus-restore"
for v in p["spec"]["volumes"]:
    if "persistentVolumeClaim" in v: v["persistentVolumeClaim"]["readOnly"]=False
for v in p["spec"]["containers"][0]["volumeMounts"]: v.pop("readOnly",None)
print(json.dumps(p))' | kubectl create -f -
kubectl -n odysseus-restore wait --for=condition=Ready pod/odysseus-backup --timeout=300s
# First list the decrypted archive and verify only expected relative paths.
age -d -i "$HOME/.config/aws-account-infra/recovery/etcd-age-key.txt" \
  "$CAPTURE_DIR/workspace.tar.gz.age" | tar -tzf -
# Run with pipefail in a separate bash script so decryption failure stops recovery.
set -o pipefail
age -d -i "$HOME/.config/aws-account-infra/recovery/etcd-age-key.txt" \
  "$CAPTURE_DIR/workspace.tar.gz.age" |
  kubectl -n odysseus-restore exec -i odysseus-backup -- \
    tar -xzf - -C /snapshot --no-same-owner workspace chromadb
kubectl -n odysseus-restore delete pod odysseus-backup --wait=true
kubectl -n odysseus-restore scale deployment/chromadb deployment/odysseus --replicas=1
kubectl -n odysseus-restore rollout status deployment/chromadb --timeout=600s
kubectl -n odysseus-restore rollout status deployment/odysseus --timeout=600s
kubectl -n odysseus-restore port-forward service/odysseus 7000:7000
```

The production configuration requires Secure cookies. For local HTTP-only restore
inspection, temporarily set `SECURE_COOKIES=false` and
`ALLOWED_ORIGINS=http://localhost:7000` **only on the isolated Deployment** using
`kubectl -n odysseus-restore set env deployment/odysseus ...`; leave authentication
enabled and localhost bypass disabled. Verify saved login, conversations, settings,
uploads and vector collections against a prepared canary. New model inference and
web search are intentionally unavailable in the isolated namespace. Record results,
elapsed recovery time, and any missing data in the OpenSpec tasks. Keep the original
encrypted backup. Explicitly remove the rehearsal namespace when finished; retained
local PVs may need separately reviewed cleanup after confirming their claim namespace.

A real recovery uses fresh production PVCs after infrastructure recovery, protected
credentials restored/reissued, this data restore, then CI reconciliation. Re-pull
models from the captured inventory and verify their digests and CPU smoke inference.
