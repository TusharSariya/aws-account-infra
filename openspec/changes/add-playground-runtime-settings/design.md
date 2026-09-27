## Context

The AI Pod requests 31.35 CPU and 77 GiB, the entire reviewed worker pool (31.25 CPU / 84 GiB with a 6.5 CPU / 24 GiB platform reserve). Ticket #255 on map #237 chose "a dedicated ClusterQueue with a reserved slice"; a literal slice is impossible because the runtime needs everything. Measured on 2026-09-26: a 2-CPU ARC runner left the runtime 1.6 CPU short and BestEffortFIFO admitted further runners ahead of it for 8 minutes.

## Decisions

- **StrictFIFO on the single queue, not a cohort and not preemption.** The scheduling change's contract (`test_standalone_queue_has_no_cohort_only_fields`) keeps `homelab-compute` standalone with no borrowing or fairness, so a second queue in a cohort was rejected. `StrictFIFO` gives the intended behaviour with no controller code: while the runtime waits at the head, later runners are not admitted; running runners finish and free the quota; the runtime admits. The cost, every PR waiting while the runtime is pending, is the same cost the alternative hold had.
- **Nothing else moves.** Quota numbers, the coordinator's reconciler, CI quota checks, the lifecycle's queue visibility and RBAC are untouched.
- **Gateway message.** `gateways.json` entries may carry `message`; the chart passes it as `WAKE_MESSAGE` and the gateway falls back to the previous text. A cold `GET` already sends `Refresh: 10` for HTML clients.
- **KV cache.** q8_0 with flash attention forced on, server-wide, per the fit rule; measured RSS after rollout is recorded on the map.

## Risks

StrictFIFO also holds CI runners that would fit on the secondary worker while the runtime waits at the head; accepted for the minutes it takes. A runtime that can never fit (misconfigured request) would block the queue; the lifecycle's Stop clears it, and CI already surfaces queue position.
