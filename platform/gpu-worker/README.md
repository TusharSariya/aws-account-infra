# Ubuntu GPU worker and durable inference

Implementation branch: `feat/ubuntu-gpu-inference`. Tracking: [issue #212](https://github.com/TusharSariyaOrg/aws-account-infra/issues/212).
The gateway and worker resources are opt-in. Live VM enrollment and hardware
acceptance are still pending; see [evidence](evidence-20260923.md).

## Ownership and bootstrap

OpenTofu owns the disposable VM; fresh Ansible roles own Ubuntu; the existing
management Helm/OpenTofu root owns plugin, RuntimeClass, Kueue queues, enrollment
RBAC, gateway and controllers. Runtime Pods are reconciled by the versioned
controller delivered by that chart. Ansible never provisions Talos or charts.

Adopt Ubuntu 26.04 on the separate desktop drive and existing SSH access first.
Record disk serials, Windows boot entry, Secure Boot, Wi-Fi chipset and storage.
Installation, initial SSH, interactive sudo, optional Tailscale login and MOK
approval are bootstrap prerequisites. No automation changes the boot order,
formats disks, or powers the desktop. Existing AI services/PVs remain unchanged.

The verified main kubeconfig is on `tushar@10.0.0.181` at
`~/.local/share/main-control-plane/private/kubeconfig`, with adjacent `kubectl`.
Its API is `https://10.0.0.231:6443`, and kube-system UID is
`43b9d80f-4676-49c0-84ab-87d3666691dc`. The Mac default kubeconfig is historical.
Do not substitute pilot credentials. No cluster-admin kubeconfig reaches a worker.

## Ordered rollout

1. Land and deploy the power-controller ownership fix through its existing laptop
   installation workflow. Test foreign desktop Workloads and malformed owned
   flavors. A malformed server reservation blocks retirement and remains Pending;
   it does not crash admission for the other server Workloads.
2. Use the existing `powerctl` maintenance hold and wake path for the primary,
   verify restoration is complete, and plan the
   [disposable validation root](../../live/proxmox/ubuntu-validation/README.md).
   This VM uses DHCP and a dedicated VM ID. Capture and retain local state until
   destruction. Never start stale VM 100.
3. Install Ubuntu roles in that VM using private inventory and public operator
   keys. Start with `worker_enrollment_enabled: false`; review check/diff, apply,
   repeat apply, then reboot and verify actual convergence.
4. Enable `workerEnabled` in the management chart, using the device-plugin digest
   in `versions.json`. Keep `enabled: false` and all quotas at zero. This installs
   enrollment RBAC and validation resources without admitting inference work.
5. Run `enroll.py --kubeconfig PRIVATE --node ubuntu-enrollment-validation
   --output PRIVATE/enrollment.json` on the trusted operator host. It creates a
   15-minute bootstrap token and a mode-0600 private vars file. Merge that file at
   Ansible invocation, set `worker_enrollment_validation_vm: true` and
   `worker_enrollment_enabled: true`, and apply the same enrollment role in the VM.
   Bootstrap token authentication must be enabled on the existing API server;
   verify it rather than editing Talos configuration speculatively.
6. Verify the initial CSR: token identity from the private enrollment file,
   signer `kubernetes.io/kube-apiserver-client-kubelet`, subject
   `CN=system:node:ubuntu-enrollment-validation,O=system:nodes`, requested usages
   and public key fingerprint observed from the VM. Approve only that CSR.
   Verify serving CSRs separately: signer `kubernetes.io/kubelet-serving`, matching
   node identity and only its observed IP/DNS SANs. Never blanket-approve CSRs.
   Test client rotation and serving renewal before rollout. The gateway includes a
   serving-CSR approver restricted to accepted node UIDs, authenticated node identity,
   signer/usages and fixed IP/DNS SANs. Its RBAC approves only the serving signer;
   initial VM/desktop bootstrap is still inspected before enabling that controller.
7. Prove node Ready, Cilium, cross-node traffic, service DNS, API-to-kubelet
   logs/exec, and reboot recovery. Cilium currently uses `localhost:7445`; Ubuntu's
   HAProxy provides TCP passthrough to the main API. Verify its TLS behavior and
   Talos API egress assumptions in the VM. Do not globally change Cilium based
   on a render. Record evidence, then remove VM enrollment and destroy only its
   OpenTofu root. Release the maintenance hold.
8. Only after the VM passes, prepare desktop private vars (example below), then
   review/check, apply with interactive sudo, repeat apply, and reboot manually.
   Set `worker_enrollment_vm_accepted: true` only against recorded VM evidence.
   Use a fresh 15-minute token. Bootstrap credentials are removed after a client
   certificate appears; kubelet client rotation uses node-scoped RBAC.
9. While the desktop is quarantined, use explicitly tolerated acceptance Pods to
   validate Cilium/DNS, CUDA and the cached Qwen model on CPU and CUDA. Record
   allocatable CPU/RAM and free scratch after reservations/cache. Populate measured
   Helm values; CPU/RAM are additionally capped at 12/24 GiB, GPU at one.
10. Validate each candidate profile in `profiles.example.json`, including old-server
    CPU instruction support. Cache the exact same model/checksum on every backend.
    The server runtime init container atomically caches the checksum-pinned model in
    a dedicated `/var/lib/homelab-inference/models` directory. Ubuntu cache remains
    Ansible-owned. Neither path mounts or overwrites existing AI storage. The generic CPU
    image is a candidate, **not yet proven on the older server CPUs**.
11. Build `apps/platform/inference/Dockerfile`, publish with `.github/workflows/inference-image.yml`, and pin its digest in Helm `image`; it includes the pinned cryptography
    dependency for serving-CSR validation. Pin accepted node UIDs and enable only proven profiles. Create external Secret
    `inference-gateway-auth` with key `token` (at least 32 random characters), without
    committing or printing it. Enable the gateway through management OpenTofu.
    For the private published gateway image, create a read-only registry Secret in
    `homelab-inference` and reference it through Helm `imagePullSecrets`; credentials
    remain outside Git. Its SQLite directory `/var/lib/homelab-inference` is local to the laptop's
    control-plane VM, persists reboots, and needs at least 1 GiB free. It is not an
    off-host backup; include it in laptop recovery. Existing DNS/AI volumes are not
    used. Verify gateway resource headroom and existing PV bindings after apply.
12. Run the full acceptance matrix below. Keep admission disabled for any unproven
    backend. Record versions, node UID/boot ID, command output and results.

Private desktop variables (save outside Git, mode 0600):

```yaml
worker_host_authorized_keys: ['ssh-ed25519 YOUR_EXISTING_PUBLIC_KEY']
worker_host_wifi_ssid: Rogers
# Existing system-owned Wi-Fi credential is retained when PSK is omitted.
worker_host_tailscale: false # enable after interactive login, with an exact package version
worker_cache_assets:
  - name: Qwen3-0.6B-Q8_0.gguf
    url: https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/23749fefcc72300e3a2ad315e1317431b06b590a/Qwen3-0.6B-Q8_0.gguf
    checksum: sha256:9465e63a22add5354d9bb4b99e90117043c7124007664907259bd16d043bb031
worker_cache_images: [] # populate from versions.json plus digest-pinned smoke images
worker_enrollment_enabled: false
```

Interactive commands are in [ansible/README.md](../../ansible/README.md). Credentials
are supplied using a second `-e @/PRIVATE/enrollment.json`, never command-line token
literals. The public CA and bootstrap token are the only enrollment material copied.

## Request contract

Access is opt-in through `kubectl -n homelab-inference port-forward
service/inference-gateway 8080:8080` using main-cluster credentials. No unauthenticated
LAN ingress is created. Use `Authorization: Bearer TOKEN` over this local tunnel.

- `POST /v1/chat/completions`: OpenAI-compatible text messages/model/max_tokens,
  optional `stream`, plus `policy` and explicit `retry_safe`. Admission expires at
  30 seconds. Execution defaults to a 120-second hard connection deadline.
- `POST /v1/requests`: same body, without streaming; returns 202, request ID and
  status URL. Queuing can wait durably across controller/node restarts.
- `POST /v1/batches`: `{ "requests": [{ "id": "stable-id", "policy": "cpu-only",
  "retry_safe": true, "body": { "model": "Qwen3-0.6B-Q8_0", "messages": [...] }}] }`.
  Up to 64 items, HTTP 207 with per-item outcomes. Admission is intentionally
  per-item, not an atomic batch transaction; resubmit stable IDs after interruption.
- `GET /v1/requests/ID` reports state, backend and attempt; `/result` returns the
  durable published result or 409 while unavailable. Bodies/results are authenticated.
- `Idempotency-Key` on single submissions deduplicates work; reuse with a different
  payload is rejected. Batch item `id` has the same semantics. A live stream cannot
  be resumed or silently replayed; a duplicate stream submission returns 409.

Policy selection is GPU preferred -> immediately free GPU, then desktop CPU, then
server CPU; GPU required queues only for GPU; CPU only never receives GPU access.
Each runtime is a single Kueue-reserved Pod. Live and batch requests share that
reservation and one execution slot; they never create per-request GPU Pods.
Each backend dispatches three live calls then one batch item when both wait.
SQLite records requests, selected execution backend, attempts, generations, fairness
and results transactionally. CPU runtimes release their Pods after five idle minutes.

Only explicitly retry-safe requests retry, at most three attempts. Reconciliation
never treats Wi-Fi loss, timeout, a missing Pod, or a replacement Pod UID as proof of
termination. Such work retains its slot as `uncertain`. A completed response can
settle it; a healthy observed node reboot or authoritative terminal Pod status can
fence it. Streams never retry, even when retry_safe was requested. Results publish
once per request; external effects still have at-least-once semantics for opted-in
retries. No API exists to force-clear uncertain work without fencing.

Requests are <=64 KiB, results <=1 MiB, max_tokens <=4096, and HTTP concurrency is
bounded at 32. SQLite retains at most 512 request records including terminal results;
when full, admission returns 429. **Retention/export automation is not included**;
archive a closed database with its idempotency history before resetting the service.
Do not remove completed IDs from a live store, which would allow resubmission.

## Acceptance matrix

| Gate | Required evidence |
| --- | --- |
| VM | actual apply/reapply, TLS bootstrap and rotation, serving cert renewal, Cilium, DNS, logs/exec, reboot |
| Desktop | Windows preserved, Secure Boot, actual apply/reapply, GPU CUDA, same-model CPU/CUDA output, scratch measurements |
| Scheduling | shared quota, GPU required wait, CPU-only isolation, desktop then server fallback, live/batch 3:1, additional backends |
| Recovery | Ubuntu reboot, Windows boot, Wi-Fi loss, controller restart, timeout, interrupted stream, stale result/duplicate prevention |
| Independence | desktop inference with both servers off and assets cached locally |
| Controlled wake | CPU fallback wakes through owned Kueue server reservation; GPU-only wait does not wake servers |
| Non-regression | existing services/PV bindings, power management and laptop resource headroom |

`health.py` writes read-only observations and always marks acceptance incomplete;
it cannot infer the functional gates from Node Ready. CI tests complement these
live checks and cannot replace them.

## Rollback

Disable gateway admission first (`enabled: false`); keep the SQLite directory and
external secret. Record/fence running requests before removing runtime Pods. Set
the desktop quarantine taint, stop/disable its kubelet through Ansible, and delete
only its Kubernetes Node and expired bootstrap token after verifying identity.
Disable `workerEnabled` to remove its plugin/queues/RBAC. Preserve `/var/lib/kubelet`
for investigation or explicitly revoke enrollment credentials before re-enrollment.
Leave Windows, manual power controls, existing Talos nodes and all AI data untouched.

## Sources

[Kubelet TLS bootstrap](https://kubernetes.io/docs/reference/access-authn-authz/kubelet-tls-bootstrapping/),
[certificate rotation](https://kubernetes.io/docs/tasks/tls/certificate-rotation/),
[Cilium/Talos local API behavior](https://docs.cilium.io/en/stable/installation/k8s-install-helm/),
[NVIDIA Toolkit installation](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html),
[llama.cpp server](https://github.com/ggml-org/llama.cpp/blob/master/tools/server/README.md),
[Qwen model](https://huggingface.co/Qwen/Qwen3-0.6B-GGUF),
[Ansible check mode](https://docs.ansible.com/projects/ansible/latest/playbook_guide/playbooks_checkmode.html).

Prepared operator invocation on this workstation (private variables already exist;
enrollment is disabled):

```sh
cd /Users/tusharsariya/Projects/aws-account-infra-gpu-worker
export ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg"
ansible-playbook -i ansible/inventories/example/gpu.yml ansible/playbooks/ubuntu-worker.yml \
  -e @/Users/tusharsariya/.config/aws-account-infra/gpu-worker/worker-vars.json \
  --ask-become-pass --check --diff
```

Review before removing `--check --diff` for apply. Keep enrollment disabled until
the disposable-VM proof is recorded. The private vars file contains the existing
public SSH key and pinned cache references; it contains no reusable cluster admin
credentials or Wi-Fi secret. Use `worker-retire.yml` for the host rollback step.

VM proof recorded in [the evidence file](evidence-20260923.md): actual convergence,
quarantined enrollment, Cilium, DNS/API, reboot and basic older-CPU inference pass.
For future proofs run `helm test homelab-inference -n kueue-system` and read logs
with `kubectl -n homelab-inference logs ubuntu-worker-validation` (the test Pod
namespace differs from its Helm release). Delete the test Pod after evidence capture.
Desktop check/apply remains interactive; do not infer GPU acceptance from the VM.

Ubuntu 26.04 desktop escalation uses the installed `/usr/bin/sudo.ws` via
`ansible_become_exe` in inventory. The default sudo-rs 0.2.13 wraps Ansible's
custom prompt; ansible-core 2.21.1 does not recognize it and times out before
sending the password. A direct SSH prompt probe against both binaries confirmed
the mismatch with Ansible's actual prompt matcher. This selects an executable
for Ansible only and does not change the host sudo alternatives or sudoers policy.
See [Ubuntu sudo-rs compatibility documentation](https://ubuntu.com/server/docs/reference/other-tools/sudo-rs/).

After desktop convergence, run cached same-model CPU/CUDA acceptance locally:

```sh
ANSIBLE_CONFIG="$PWD/ansible/ansible.cfg" ansible-playbook \
  -i ansible/inventories/example/gpu.yml \
  ansible/playbooks/worker-inference-check.yml --ask-become-pass
```

This creates temporary validation inputs and UUID-named containers, uses loopback
HTTP only, checks the cached model checksum and CUDA process GPU allocation, and
cleans up after success/failure. It neither enrolls the node nor enables admission.
Temporary-file changes in this acceptance playbook are expected; convergence is
measured by the main worker playbook. Keep its CPU and CUDA completion evidence.

TPM auto-unlock is now an interactive bootstrap prerequisite for this desktop:
Clevis binds the existing LUKS volume to TPM2 SHA256 PCR7 while preserving its
passphrase. Keep a protected header backup outside the encrypted root and retain
the passphrase for firmware/Secure Boot recovery. Follow
[Ubuntu's Clevis/Dracut procedure](https://ubuntu.com/server/docs/how-to/security/tpm-backed-luks-decryption-with-clevis/).
The `worker_unlock` role owns pinned packages, boot-image regeneration after package
changes and binding verification. It never reads a passphrase or creates/removes
keyslots. The operator-tested binding and reboot evidence are recorded separately;
the newly added role still needs its own interactive convergence check. Other
Ubuntu hosts default to `worker_unlock_enabled: false`.
