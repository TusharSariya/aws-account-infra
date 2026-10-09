# Adversarial review brief (model comparison run)

Review target: the git worktree at the repository root (detached at commit 000bb81, current `main`). Review ONLY files in that worktree.

## Rules
- READ-ONLY. Do not edit files, commit, run `tofu apply`, `helm`, `kubectl`, `talosctl`, `ssh`, `gh`, or any command that touches live infrastructure, GitHub, or the network. Repo reading only (cat, grep, find, git log/show within the worktree).
- Do not read `docs/reviews/` or any other prior review; form your own findings.
- Never print secret values.

## System under review
A Talos Linux Kubernetes homelab: a single control plane (Talos VM on an Ubuntu laptop) and two Proxmox servers, each hosting one Talos worker VM. Workers sleep and wake automatically (see `platform/automatic-power/`). IaC: OpenTofu roots under `live/`, Helm charts under `charts/`, config under `config/environments/`, platform tooling under `platform/` and `kubernetes/`, CI under `.github/`, plans under `docs/plans/`, runbooks under `docs/runbooks/`, OpenSpec changes under `openspec/`.

## Operator goal
A production-like homelab that can run private apps and accept public internet traffic safely; run AI (incl. GPU) workloads scheduled, on-demand, or persistent; handle security-, performance-, and latency-sensitive work; stay modular and maintainable; and add/remove heterogeneous workers (e.g. a GPU server).

## Required output (exactly this structure, under 1500 words)
1. **Verdict** for your angle: one paragraph.
2. **Findings**, numbered F1, F2, ... ranked by severity. For each:
   - Severity: Critical / High / Medium / Low
   - Claim: one sentence
   - Evidence: `path:line` citations (must be real lines in the worktree), quotes where useful
   - Status: IMPLEMENTED-BUT-FLAWED / MISSING / PLANNED-ONLY
   - Failure scenario: concrete
   - Fix: concrete
   - Confidence: High / Medium / Low
3. **Strengths**: up to 5 bullets.
Precision matters more than volume: every finding will be checked against the code and false claims count against you.
