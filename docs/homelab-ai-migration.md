# Default-off AI packaging and single-use volume migration

The second rollout stage publishes one four-container Pod template as `ai-approved-template`. Helm does not create a runtime Deployment. The later lifecycle controller owns its runtime replica count and desired state. The approved default is zero replicas and `off`; legacy Ollama, Odysseus, Chroma and Searx Deployments remain present at zero replicas. Pi-hole retains its independent release and live DNS/HTTPS checks.

The aggregate requests and limits are 35.75 CPU and 77 GiB: Ollama 34 CPU/64 GiB, Odysseus 1 CPU/8 GiB, Chroma 500m/4 GiB and Searx 250m/1 GiB. Scheduling is atomic because all four containers share a Pod. Insufficient capacity leaves the whole Pod Pending. Platform controllers and migration jobs have separate budgets.

Three explicitly bound static local PVs retain data on the worker's `ai-models`, `ai-workspace` and `ai-vector` project directories. Their declared sizes are 300, 20 and 10 GiB. XFS project quotas enforce these bounds; Kubernetes claim declarations alone do not. Each application mounts only its own claim. The Pod requires `hostUsers: false` to prevent project-ID escape. Disk-backed temporary volumes have separate size limits, and container writable layers have ephemeral-storage limits. Those Kubernetes controls trigger kubelet eviction rather than synchronous quota write rejection.

## Prerequisites

Complete the reviewed storage foundation, host/client credential enrollment, worker quota activation and actual user-namespace/volume acceptance. Continuous guest and physical collectors must be enabled and healthy before migration. This stage's new `enabled: true` capacity configuration must not be deployed before the independent Secret and host endpoint are enrolled. The guarded Helm apply waits for collector readiness.

Apply this stage through the existing saved-plan CI gate. It stops legacy writers and creates retained destination claims without deleting any old claim or PV. Existing destructive-action protection stays intact; only the exact new Helm release is added to the allowlist. No general delete/replacement allowance is necessary. Routine deployment never invokes reset code.

## Authorized reset

After reviewing the exact stage and any separately desired application backup, dispatch `homelab-ai-migration` from `main`, in the protected `prod` environment, with confirmation `reset-three-ai-volumes-v1`. It serializes with infrastructure applies and refuses any other branch or confirmation.

The workflow reads the three existing claims `ollama-models`, `odysseus-data` and `chromadb-data` in `homelab-models`. It pins their claim UIDs, PV names/UIDs and exact provisioner paths in immutable ConfigMap data at `homelab-platform/ai-volume-reset-v1`. It verifies fresh independent capacity below warning thresholds and that the old Deployments are at zero with no Pods referencing these claims.

A separate restricted platform Job verifies the receipt, current bindings, worker filesystem UUID, empty quota-enforced destination directories and stopped writers again. It changes the receipt's phase from `prepared` to `started` using a resource-version compare-and-swap before deleting any data. Deletion walks anchored directory descriptors, never follows symlinks, refuses other filesystems, and only empties the three pinned old directories. Unrelated claims, directories and Pi-hole data are outside its input set. Completion is recorded only after all three resets finish.

The Job has no retries. The immutable receipt is never deleted by CI, and rerunning the workflow fails to create that existing receipt. A started or completed receipt cannot be replayed by the reset process. Keep the old retained claims/PVs at zero writers as a record; their configured retention does not restore erased content.

## Interrupted migration and recovery

A failed or interrupted Job may have completed none, some or all deletions. Do not delete the receipt or retry the Job. Inspect its immutable object identities, phase and Job status through protected administrative access. Resolve any partial state through a separately reviewed maintenance change scoped to that receipt. This workflow deliberately cannot infer whether an ambiguous reset should be repeated.

Configuration rollback cannot recover deleted application data. Recovery requires a separately captured application backup, reconstruction of quota-enforced destinations and a verified isolated restore. Neither retained PV metadata nor OpenTofu state is a data backup. No restore or recovery success is claimed by these scripts.

Keep AI off after migration until lifecycle admission, activity tracking and authenticated model access have passed the third-stage review. The template's runtime network policy currently denies traffic; publishing a template is not evidence of a working lifecycle service. Actual stop/start persistence, Pending behavior alongside Pi-hole DNS and user-namespace quota escape rejection remain live acceptance tasks.
