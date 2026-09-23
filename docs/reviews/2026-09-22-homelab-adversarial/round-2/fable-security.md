I have what I need. Final report follows.

---

# Adversarial security review: Talos homelab (worktree @ 000bb81)

## 1. Verdict

The in-cluster posture is unusually disciplined for a homelab: digest-pinned images, `restricted` PSA on tenant namespaces, default-deny NetworkPolicies plus `kube-apiserver`-entity CiliumNetworkPolicies, CEL `ValidatingAdmissionPolicy` gating Kueue/Argo pods, token-projected service accounts, and a guarded CI apply path that verifies the cluster identity fingerprint. The weak points are at the edges the cluster does not control: the self-hosted CI runners are `privileged: true` pods on the same shared worker that hosts Postgres, Nexus, monitoring and the Tailscale operator's OAuth secret, and they execute code from any same-repo PR; the tailnet still runs the allow-all policy while a restrictive one sits unapplied in the repo; `tofu-apply` deploys to prod from an unmerged PR on a label with no environment reviewer; and there is no audit-log shipping, runtime detection, image-signature verification, or public-ingress design implemented. Public internet exposure is not implemented at all today, which is the correct state until the items below land.

## 2. Findings

**F1 — Severity: High.** Claim: Same-repo PR CI runs as `privileged` containers on the shared production worker, so anyone with push access (or a stolen collaborator token) gets root on `talos-worker-01`.
Evidence: `config/environments/kubernetes/homelab-ci/arc-runner-values.yaml:61` (`dind` `securityContext: {privileged: true}`), `:78` (runner `privileged: true`), `:29` (`nodeSelector: talos-worker-01`); `charts/homelab-queue/templates/queue.yaml:4-6` (`arc-runners` PSA `privileged`); `.github/actions/talos-runner-setup/action.yml:63-64` (`sudo mknod /dev/net/tun` proves device creation works inside the pod); `.github/workflows/tofu-plan.yml:218` and `.github/workflows/tflint.yml:20` (PR jobs on `homelab-talos-checks`); `config/environments/kubernetes/homelab/operator-values.yaml:9` (Tailscale operator co-located on worker-01); no NetworkPolicy targets `arc-runners` (none in the chart/policy inventory).
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: a PR modifies a workflow step to `mknod /dev/sda` + mount, or `nsenter -t 1`, reads `/var/mnt/local-path-provisioner` (Postgres, Nexus data), dumps the `tailscale/operator-oauth` Secret via the node's kubelet credentials, and enrolls attacker devices into the tailnet.
Fix: run runners under the gVisor `runsc` RuntimeClass already present on the workers (`kubernetes/platform/two-worker/worker-join-smoke.yaml:12-15`) with rootless/sysbox-style DinD or Kaniko; drop `privileged`; move the Tailscale operator and secrets-bearing workloads to a different node or trust class; add a default-deny NetworkPolicy for `arc-runners`; require `environment: prod` approval for any job on self-hosted runners.
Confidence: High.

**F2 — Severity: High.** Claim: The Talos cluster root secrets bundle (`TALOS_SECRETS_B64`) is handed to CI jobs that run on those same privileged in-cluster runners, and to the `prod` environment that has no required reviewer.
Evidence: `.github/workflows/tofu-plan.yml:218-251` (`applications-plan` on `homelab-talos-checks` when `CI_EXECUTOR=talos`, `environment: prod`, `secrets-b64: ${{ secrets.TALOS_SECRETS_B64 }}`); `.github/workflows/tofu-apply.yml:44` (kubernetes unit apply also on `homelab-talos-checks`); `scripts/talos-ci.py:185-190` (bundle decoded, written, used to regenerate a full `talosconfig`); `scripts/homelab-talos-config.py:57-58` (`--with-secrets ... talosconfig`, i.e. `os:admin`); `live/proxmox/homelab/CI.md:23-26` ("`prod` currently has no required-reviewer protection").
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: the F1 attacker (or a malicious same-repo workflow edit) exfiltrates the bundle; the attacker now holds the Talos CA, Kubernetes CA, etcd CA and can mint `os:admin`/`system:masters` credentials indefinitely; rotation requires a cluster rebuild.
Fix: pin all jobs that consume `TALOS_SECRETS_B64` to `ubuntu-latest` (as `talos-homelab`/`proxmox-homelab` already are); add required reviewers to `prod`; issue CI a short-lived `os:operator` talosconfig via `talosctl config new --roles os:operator` from a workstation, and keep the root bundle only in the encrypted S3 archive.
Confidence: High.

**F3 — Severity: Medium.** Claim: The tailnet runs the default allow-all policy; the restrictive grant policy is committed but explicitly unapplied, so every tailnet device (including CI ephemeral nodes tagged `tag:github-ci`) can reach Proxmox 8006, Talos 50000, the K8s API, Ollama, Argo, Pi-hole admin, etc.
Evidence: `config/environments/proxmox/homelab/tailscale/README.md:3-4` ("retain the existing default allow-all policy"), `:8` ("not an applied policy"); `live/proxmox/homelab/CI.md:60-62` ("allow-all tailnet network policy still applies to the CI runner"); `live/kubernetes/homelab/README.md:55-57`; `charts/homelab-ollama/templates/resources.yaml:87-89` (unauthenticated Ollama Ingress on tailnet).
Status: PLANNED-ONLY.
Failure scenario: any compromised phone/laptop on the tailnet, or a CI runner node, reaches the Proxmox UI and Talos API surfaces and unauthenticated Ollama/Odysseus.
Fix: apply `policy.json` with grants split by `tag:github-ci` (only 6443/50000 to CI), `tag:k8s` proxies (only 443/53), and admin devices; put Tailscale Access/Authentik in front of app Ingresses.
Confidence: High.

**F4 — Severity: Medium.** Claim: The laptop control-plane host holds the cluster's entire root of trust in cleartext at rest with no Talos disk encryption and no evidence of host FDE.
Evidence: `platform/main-control-plane/launch.sh:19-21` (`system.qcow2`, `dns.qcow2` plain qcow2), `:16` (OVMF vars writable); `config/environments/proxmox/homelab/talos/patches/common.yaml:1-12` and `talos-cp-01.yaml` contain no `systemDiskEncryption`/`VolumeConfig` encryption; no `luks|encrypt` hits in `docs/runbooks/main-control-plane.md`; the coordinator uses the full admin `talosconfig` (`platform/automatic-power/coordinator.example.json:11`) and a never-expiring SA token Secret (`charts/homelab-always-on/templates/coordinator.yaml:7-14`, `helm.sh/resource-policy: keep`).
Status: MISSING.
Failure scenario: laptop theft or a stolen `tushar` session yields etcd (all Secrets), the Talos PKI, and a non-expiring node-patch token.
Fix: enable Talos STATE/EPHEMERAL encryption (TPM or static key) on the CP VM, verify LUKS on the Ubuntu host, replace the coordinator's `os:admin` talosconfig with `os:operator`, and swap the legacy token Secret for a bound projected token or TokenRequest with rotation.
Confidence: Medium (host FDE unknown from repo).

**F5 — Severity: Medium.** Claim: `tofu-apply` applies to prod from an unmerged PR branch on the `apply` label, with no environment approval.
Evidence: `.github/workflows/tofu-apply.yml:3-5` (`pull_request: [opened, synchronize, reopened, labeled, unlabeled]`), `:43` (`contains(labels, 'apply')`), `:45` (`environment: prod`), `:137-153` (`apply -auto-approve`); `live/proxmox/homelab/CI.md:23-24`.
Status: IMPLEMENTED-BUT-FLAWED.
Failure scenario: a collaborator labels a PR that has a subtly changed Helm value or workflow; live Talos/Kubernetes/Proxmox change without a merge review; `synchronize` events after labeling re-apply new pushes.
Fix: require `prod` reviewers; only apply from `push` to `main` or from a `workflow_dispatch` with a plan hash; remove `synchronize` from the apply trigger.
Confidence: High.

**F6 — Severity: Medium.** Claim: There is no security telemetry: API audit logs are not configured or shipped, no runtime detection, and alerts cover only availability.
Evidence: no `auditPolicy`/`admissionControl` in `config/environments/proxmox/homelab/talos/**` or `scripts/homelab-talos-config.py`; `kubernetes/platform/main/monitoring/config/alloy.alloy` has no audit/journal source; `kubernetes/platform/main/README.md:48-52` ("No host logs ... collected"); `alerts.yml:4-19` (four availability alerts only); Tetragon is plan-only (`docs/plans/kubernetes-security-hardening-2026.md:236-239`).
Status: MISSING (hardening doc's "API audit policy" claim at `:46-47` describes the retired kubeadm path, not Talos).
Failure scenario: F1/F2 exploitation leaves no durable trace; Talos default audit logs on the CP VM disk are lost with the VM.
Fix: set `cluster.apiServer.auditPolicy` in `common.yaml`, ship `/var/log/audit/kube` via Alloy or `talosctl logs`, add RBAC/Secret-access alerts, deploy Tetragon observe mode.
Confidence: High.

**F7 — Severity: Low.** Claim: No image signature verification; supply chain relies on digest pinning only, and Talos CLI/installer integrity checks are SHA-only.
Evidence: no `cosign|sigstore` in `.github`, `scripts`, `charts`; `config/environments/proxmox/homelab/talos/README.md:18-19` ("Sigstore signature verification ... remain recovery-foundation work"); Kyverno/Sigstore in `docs/plans/kubernetes-security-hardening-2026.md:28` only.
Status: PLANNED-ONLY.
Failure scenario: a GHCR push from a compromised Actions run (`ghcr.io/tusharsariyaorg/homelab-ci-runner`) is later pinned by digest in a PR and admitted.
Fix: sign with `cosign` keyless in the image workflows; enforce with a `ValidatingAdmissionPolicy`/Kyverno `verifyImages` on `arc-runners`, `homelab-models`.
Confidence: High.

**F8 — Severity: Low.** Claim: Public-internet ingress is not implemented; the roadmap's Cloudflare Tunnel + Access design is unbuilt.
Evidence: only `ingressClassName: tailscale` Ingresses exist (`charts/homelab-jobs/templates/access.yaml:50`, `charts/homelab-lifecycle/templates/resources.yaml:176`, pihole-values `:57`); design in `docs/plans/production-kubernetes-homelab-roadmap.md:27-28, 88-101`.
Status: PLANNED-ONLY (correct current state; noted so no one assumes it exists).
Fix: build cloudflared per the roadmap only after F1, F3, F6 are addressed.
Confidence: High.

## 3. Strengths

- CEL admission (`charts/homelab-queue/templates/admission.yaml`, `charts/homelab-jobs/templates/admission.yaml`) tightly bounds tenant pods and Argo workflows, including "only Kueue may remove its gate".
- Consistent default-deny plus `toEntities: [kube-apiserver]` CiliumNetworkPolicies for `homelab-cache`, `homelab-data`, `homelab-platform`, `homelab-jobs`, `argocd`, and per-gateway policies in `homelab-always-on`.
- CI identity guard: `identity.json` SHA pinning, `guard_plan` rejection of bootstrap/create, `prevent_destroy` and `no_reboot` on Talos resources, write-only/ephemeral variables so no credentials land in state.
- Tailscale operator with `apiServerProxyConfig.mode: 'false'`, `allowImpersonation: 'false'`, dedicated OIDC trust scoped to `repo:...:environment:prod`, and Funnel deliberately unused.
- Digest-pinned images across charts and values; projected 1h service-account tokens; `automountServiceAccountToken: false` by default.