> Raw agent report from the 2026-09-22 homelab adversarial review. It was produced against a local working tree behind `main`; several findings were fixed on `main` (`000bb81`) before filing. See [README.md](README.md) for the re-verified status and issue links.

I've read the brief, CONTEXT.md, deploy-units.json, both Proxmox roots, the Argo CD manifests, the READMEs, the CI workflows and git status. I did not run any cluster commands.

# Review B: architecture, maintainability, IaC and GitOps

## 1. Verdict per goal

1. **Private apps and safe public traffic: NOT MET.** Argo CD is installed with no working applications, and no ingress or exposure path is implemented in code.
2. **AI and GPU workloads: NOT MET.** There is no GPU code at all. `grep -ri nvidia|gpu` over `kubernetes/`, `platform/`, `live/proxmox/` and `config/environments/proxmox/` finds nothing. `kubernetes/platform/two-worker/README.md` says "There is intentionally no AI queue."
3. **Security-, performance- and latency-sensitive work: PARTIAL.** Placement labels, Kueue flavors and the gVisor placement mentioned in the secondary root README are designed. Kueue is "not installed by this repository yet", and I did not trace whether any other placement pieces are deployed.
4. **Modular and maintainable, add or remove heterogeneous workers: NOT MET.** Worker roots are copy-pasted and hard-coded to exact capacity numbers. Most of the logic lives in bespoke Python. Almost none of it is in Git.
5. **Arbitrary workloads, production-like: NOT MET.** There is no onboarding path, no GitOps reconciliation loop, and the CI workflows are not committed.

## 2. Findings by severity

### Critical

**C1. The whole homelab platform is outside version control.**
- **Evidence:** `git ls-files pilot kubernetes platform live/proxmox validation` returns only 2 files, both `kubernetes/apps/pihole/*.sh`. There are 848 untracked files, including all of `kubernetes/platform` (42), `platform/main-control-plane` (24), `live/proxmox` (16), `pilot/*`, `config/environments/proxmox`, the runbooks, and all four new workflows. `.github/workflows/ansible.yml` is deleted but that deletion is not committed.
- **Failure scenario:** The laptop disk fails. It is also the control-plane host and holds the only copy of the "desired state". CONTEXT.md defines "Recovery-critical service" as "committed desired state", and none of this state is committed. The DR story is fiction until it is pushed.
- **Fix:** Commit it in reviewable slices, with `graphify-out/`, `.repowise/`, `__pycache__` and `.ruff_cache` in `.gitignore`. Merge or push to a remote now.

**C2. GitOps is nominal, not real.**
- **Evidence:** `kubernetes/platform/main/argocd/projects.yaml` locks the `default` AppProject shut (`sourceRepos: []`, `destinations: []`). The main cluster has no `Application` or `ApplicationSet` anywhere. The platform is installed imperatively by `kubernetes/platform/main/install.py`, which calls `kubectl apply -f` / `apply -k` at lines 43, 59, 95, 121 and 151. The only Application, `pilot/argocd/application.yaml`, points at `targetRevision: main` and `path: pilot/application/manifests`. That directory does not exist locally or on main, so the app can never sync. `pilot/controllers/README.md` says "Argo was removed" from the pilot after a paging gate failed.
- **Failure scenario:** Someone runs a manual `kubectl edit`. Nothing detects or reverts it. Rebuilding the cluster means running Python scripts in an order that exists only in runbooks.
- **Fix:** Add one root app-of-apps (or an ApplicationSet over `kubernetes/apps/*`) with restricted AppProjects and sync waves. Make `install.py` responsible only for bootstrapping Argo, then hand off to it. Delete or fix the pilot Application.

### High

**H1. Docs contradict each other and the code.**
- **Evidence:**
  - CONTEXT.md line 8 says "three Talos virtual machines on Proxmox and one physically separate Ubuntu GPU worker".
  - The code says otherwise. The primary root has a `control_plane_retired` precondition for `talos-cp-01`, and the `platform/main-control-plane/` README says "The laptop is authoritative", which matches the operator's laptop control plane.
  - The roadmap (line 56) says Argo CD bootstrap happens "under Ansible", but the code bootstraps it with Python.
  - Roadmap line 112 says "The laptop remains the physical internet gateway." It is now also the only control plane, and no doc addresses that combined single point of failure.
  - The project `CLAUDE.md` still says "Kubernetes is documentation-only" and that Ansible "must not install Kubernetes". Agents working in this repo are steered by stale rules.
- **Fix:** Pick one source of truth for topology, such as a single machine-readable inventory that tfvars and Talos config derive from. Update CONTEXT.md and CLAUDE.md to match it. Put a status table in the roadmap marking each item as implemented or planned.

**H2. The two Proxmox roots are copy-paste forks with local state.**
- **Evidence:**
  - `live/proxmox/homelab/main.tf` and `homelab-secondary/main.tf` are the same resource block apart from formatting and preconditions.
  - `required_version` differs: `">= 1.11, < 2.0"` vs `"~> 1.11.0"`. This breaks the repo rule that versions stay pinned across roots.
  - Neither root has a backend. The homelab README says "No remote backend has been configured yet."
  - The secondary root's `terraform.tfstate` and `.backup` sit in the working tree. They are git-ignored, backed up "in the private join directory".
  - Both units are `"ci": false` in deploy-units.json, so `tofu-plan.yml` never runs fmt, validate or `tofu test` on them, even though `tests/vms.tftest.hcl` exists.
- **Failure scenario:** A lost laptop means lost state. The next apply tries to recreate VM 103, which the README itself warns about. Provider bumps also drift between the two roots.
- **Fix:** Extract `modules/proxmox/talos_vm`. Make each root a thin caller, or use one root with a per-node map. Add an encrypted S3 backend with a new key. The `homelab-recovery` AWS root is the obvious home. Add a CI job running `tofu fmt`, `validate` and `test` with no credentials.

**H3. Adding a heterogeneous worker (for example a GPU box) touches about 10 or more files in 5 or more languages.**
- **Evidence:** The secondary precondition requires `total_vcpus == 38 && total_memory_gib == 112 && total_guest_disks_gib == 320`, an exact equality, not a budget. Adding a worker would mean:
  - a new root or a forked tfvars;
  - `config/environments/proxmox/homelab/talos/{cluster.json,patches}` plus `scripts/homelab-talos-config.py`;
  - node labels (`homelab.tfdraw.dev/worker-role` and similar) applied by hand;
  - `kubernetes/platform/main/placement/plan.py` and the helm post-renderer;
  - Kueue flavors and caps (31.5 CPU / 92 GiB, hard-coded);
  - Cilium and network validation scripts;
  - deploy-units.json;
  - runbooks.

  Bare metal has no path at all, because the roots are Proxmox-only. There is no NVIDIA extension, device plugin or GPU Operator.
- **Fix:** Define a declarative "node class" (labels, taints, Talos patch set, Kueue flavor) rendered from one inventory. Use Talos machine-config patches for labels and taints rather than `kubectl label`. Keep the VM root generic.

### Medium

**M1. Too much bespoke code for one person to maintain.**
- **Evidence:** About 8,500 lines of Python and shell across `platform/main-control-plane` (migrate, network, maintenance, platform-state and other helpers), `pilot/*`, `validation/kubernetes` and `scripts/homelab-*`. `network.py` hand-manages TAP devices, bridges, Wi-Fi proxy neighbours and a NetworkManager dispatcher. `pilot/controllers/autoscaler.py` patches a cluster-autoscaler whose own manifests are not in the repo.
- **Fix:** Move toward declarative tools. Options include Omni or talosctl cluster templates, Argo-managed Helm with values files, and Kyverno or KEDA manifests instead of scripts. Keep scripts only as thin wrappers.

**M2. Argo CD customisation is written as escaped strings.**
- **Evidence:** `kubernetes/platform/main/argocd/kustomization.yaml` is about 12 JSON6902 patches written as escaped one-line strings. It scales several controllers to 0, deletes the upstream NetworkPolicies and deletes the Redis RBAC.
- **Fix:** Use patch files, or the upstream Helm chart with a values file.

**M3. CI only lints Python.**
- **Evidence:** The workflows run ruff, unittest, shellcheck and `validate.py`. There is no `kustomize build | kubeconform`, no policy test, no kind or Talos-in-Docker smoke test, and no tofu test for Proxmox. They are also untracked, so they run nowhere today (see C1).
- **Fix:** Add kustomize, kubeconform and conftest, plus a `talosctl cluster create` docker smoke test.

**M4. The testing strategy is scattered.**
- **Evidence:** Tests live in `validation/kubernetes`, `pilot/monitoring/tests`, `platform/main-control-plane/tests`, `tests/catalog`, `live/proxmox/*/tests` and `canaries/`, each with its own runner. Several have committed-looking `evidence/` and `runs/` directories. No single command reports platform health.
- **Fix:** Add one `make test` or task-runner target, and keep evidence out of Git or in a dated archive.

**M5. The pilot and main trees overlap.**
- **Evidence:** Argo is vendored twice (`pilot/argocd/vendor`, `kubernetes/platform/main/argocd/vendor`, plus a duplicate `crds/`). There are also two `capacity.py` and two `migrate.py` files.
- **Fix:** Retire `pilot/` or clearly archive it.

### Low

**L1. AWS staging and the homelab share one repo.** The mix is workable, because deploy-units already namespaces by cloud. But `modules/aws/encrypted_s3_bucket` is modified in the same uncommitted tree as the homelab work, so AWS and homelab changes risk landing in one PR. Split them into separate PRs at least. A separate `homelab` repo is better once Argo points at a repo URL.

**L2. Agent tooling noise in the tree.** Five agent-tooling directories (`.agent`, `.agents`, `.claude`, `.gemini`, `.opencode`) plus `graphify-out` and `.repowise` are untracked noise. Ignore them or commit them deliberately.

## 3. Blockers vs nice-to-haves

**Blockers before calling this "production-like":**
- Commit and push the homelab tree, and CI with it (C1).
- Remote encrypted state for the Proxmox roots (H2).
- A real Argo app-of-apps with a working onboarding path and self-heal (C2).
- One reconciled topology source of truth (H1).
- A shared Proxmox VM module and a node-class abstraction (H2, H3).
- A GPU enablement path, if AI is a goal.
- Manifest-level CI validation (M3).

**Nice-to-haves:** replacing bespoke scripts with declarative tools (M1), cleaning up the kustomize patches (M2), a unified test runner (M4), retiring the pilot (M5), and splitting the repo (L1).

## 4. Genuinely good

- Strong guardrails in the OpenTofu preconditions (capacity budgets, creation gating).
- A closed-by-default AppProject.
- Kueue flavors keyed on stable role labels rather than hostnames.
- Honest README caveats about local state and uninstalled manifests.
- Journaled, idempotent-by-design migration tooling.
- Pinned provider (`bpg/proxmox` 0.112.0) and pinned tool versions.
- Unit tests exist for the privileged helpers.
- The CONTEXT.md glossary is precise, even though its topology is outdated.