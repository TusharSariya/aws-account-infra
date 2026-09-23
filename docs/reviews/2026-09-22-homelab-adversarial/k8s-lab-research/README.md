# Kubernetes-internals learning lab research (2026-09-22)

Both agents got the same brief ([brief.md](brief.md)): Kubernetes-specific experimental projects for learning only, with no overlap with the distributed-systems track. Both used live web research.

| Report | Agent | Completed (-02:30) | Wall time | Tokens* |
|---|---|---|---|---|
| [codex-k8s-lab-research.md](codex-k8s-lab-research.md) | Codex `gpt-6-astra`, effort `medium`, `--search` | 23:02:21 | 252 s | 122k |
| [fable-k8s-lab-research.md](fable-k8s-lab-research.md) | Claude Fable 5.1, effort default (not settable per agent) | 23:02:53 | 282 s | 129k |

\*Token counts are as each tool reported them; they may not be counted the same way.

Review notes from the main session:
- Fable's project 5 suggests opening a snapshot of the **real** etcd offline. That snapshot contains every Secret. Treat it as sensitive material, or practise on the sandbox cluster instead.
- Fable describes the Talos default Pod Security as "restricted" here and "baseline" in its distributed-systems report. Talos enforces `baseline` by default, with `restricted` for audit and warn [check the Talos docs for your version].
- The research claims were not otherwise independently verified; [unverified] marks are the agents' own.

Each project is filed as a GitHub issue labelled `type:lab` and `lab-track:kubernetes`.
