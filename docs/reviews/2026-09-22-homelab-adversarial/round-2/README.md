# Round 2: same-angle model comparison (2026-09-22)

Three angles, each reviewed once by Claude Fable 5.1 and once by Codex `gpt-6-astra`
(reasoning effort `medium`). Both models got the same brief ([brief.md](brief.md)) and
reviewed the same pinned commit, `000bb81`. The review was read-only and repo-only, with
no network or live-cluster access. Fable's effort could not be set per agent, so it ran
at the default and was told to work at moderate depth.

The main session (Claude Opus 5.5) checked every finding against the code at `000bb81`.
The grader is a Claude model, so treat the severity and value judgements as possibly
biased. The precision tally is objective: a cited line either exists or it doesn't.

| Angle | Model | Report | Completed (-02:30) | Wall time | Tokens* | Findings | Confirmed | Partial | False |
|---|---|---|---|---|---|---|---|---|---|
| Security | Fable 5.1 (default) | [fable-security.md](fable-security.md) | 20:56:11 | 338 s | 205k | 8 | 8 | 0 | 0 |
| Security | Codex gpt-6-astra (medium) | [codex-security.md](codex-security.md) | 20:53:05 | 154 s | 53k | 8 | 8 | 0 | 0 |
| Reliability | Fable 5.1 (default) | [fable-reliability.md](fable-reliability.md) | 20:56:17 | 341 s | 168k | 10 | 9 | 1 (F9) | 0 |
| Reliability | Codex gpt-6-astra (medium) | [codex-reliability.md](codex-reliability.md) | 20:52:42 | 131 s | 70k | 6 | 6 | 0 | 0 |
| Workloads | Fable 5.1 (default) | [fable-workloads.md](fable-workloads.md) | 20:56:15 | 337 s | 165k | 9 | 8 | 1 (F1) | 0 |
| Workloads | Codex gpt-6-astra (medium) | [codex-workloads.md](codex-workloads.md) | 20:52:35 | 124 s | 83k | 6 | 6 | 0 | 0 |

\*Token counts are as each tool reported them. They may not be counted the same way, so
compare them with caution.

## Partial findings

- **Fable workloads F1:** the claim that the only always-on node is a 2 vCPU / 5 GiB VM
  is correct. The failure scenario is not: an ordinary app Deployment would not be scaled
  away, because `policy.py` blocks host shutdown while an unregistered pod is present.
- **Fable reliability F9:** the renderer does default to observe mode. But the runbook
  warns about this, the script prints "Observe-only", and it opens the destination with
  `open("x")`, so it never overwrites an existing file. "Silently" is overstated.

## Summary

- **Codex:** 100% precision, about 2.4x faster, fewer tokens.
- **Fable:** about 25% more confirmed findings, more code-path bugs (the coordinator race,
  CI secrets on in-cluster runners) and more specific line citations.
- **Overlap:** about 40% of confirmed findings were found by both models. Each model found
  high-severity issues the other missed.

Every finding maps to a GitHub issue labelled `homelab-review`. Each issue has one
attribution comment per model and effort level that found it.
