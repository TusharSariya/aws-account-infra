# Distributed-systems learning lab research (2026-09-22)

Both agents got the same brief ([brief.md](brief.md)): experimental, learning-only projects for the Talos homelab, isolated from platform services. Both used live web research.

| Report | Agent | Completed (-02:30) | Wall time | Tokens* |
|---|---|---|---|---|
| [codex-lab-research.md](codex-lab-research.md) | Codex `gpt-6-astra`, effort `medium`, `--search` | 22:50:50 | 216 s | 97k |
| [fable-lab-research.md](fable-lab-research.md) | Claude Fable 5.1, effort default (not settable per agent) | 22:51:21 | 245 s | 114k |

\*Token counts are as each tool reported them; they may not be counted the same way.

Only one claim was checked against the repo. Fable's statement that the Chaos Mesh daemon "keeps nothing awake by itself" is wrong for this cluster. `controllers/homelab-capacity/src/homelab_capacity/policy.py` registers only the `cilium`, `cilium-envoy` and `kube-proxy` DaemonSets, so any other worker DaemonSet Pod blocks host sleep. Other claims are research output, not independently verified; [unverified] marks are the agents' own.

Each project is filed as a GitHub issue labelled `type:lab`. The learning path is tracked in the lab map issue.
