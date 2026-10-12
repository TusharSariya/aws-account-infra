# Live preview verification - 2026-10-12

Inventory snapshot: `2026-10-12T19:33:36.913059+00:00`. Full live preview took 72.4 seconds; subsequent replay used the same saved event inventory with the final evidence-count presentation.

Preview warmed private activity caches under the existing lease. It did not publish either feed, change subscription URLs, or advance published revisions.

| Estimate source | Retained events |
|---|---:|
| extrapolated | 331 |
| historical | 48 |
| measured | 70 |
| published | 14 |
| Start-only | 0 |

Total: 463 retained events (251 banded, 212 unbanded). All 401 physics estimates use a route elevation profile plus a labelled coarse event lead-in; these reserve the wider 40% planning margin. There were zero missing-course events or calculation failures. The power collector completed the full inventory in two pages, with eight in-window activities and no pending or failed downloads. A warm replay downloaded no FIT files.

The independent ICS audit checked unique UIDs, absence of placeholder text, the central/reserved properties, upper-bound rounding, and the relationship between reserved duration and DTEND for every retained event. Published durations remain exact. Start-only omission and transitions are covered by executable tests.

The original screenshot was not supplied in this fresh context. This validates all retained live inventory; it does not claim a separate screenshot-to-race mapping.

## Before and after examples

| Event | Old reservation | Central estimate | New reservation | Source |
|---|---:|---:|---:|---|
| Monday Mafia - Syrup Cup - Maple Mashup [0-180, E] | 60 min placeholder | 56.7 min | 80 min | extrapolated |
| Zwift Crit Racing Club - Avon Flyer [0-180, E] | 60 min placeholder | 52.6 min | 75 min | extrapolated |
| Zwift Epic Race - Surrey Hills [0-180, E] | 60 min placeholder | 240.9 min | 340 min | extrapolated |

These are estimates from recorded efforts, not measured race predictions. In particular, long climbing events rely on extrapolation and can reserve substantially more time than the old placeholder. A 60-minute calculated estimate is valid; an unconditional one-hour end is not.

The following properties come from the same UID in the live subscription and preview. Description and revision timestamps are omitted here for readability.

Before:

```ics
DTSTART:20261012T221900Z
DTEND:20261012T231900Z
UID:5705440-7346520@zwift-calendar
```

After:

```ics
DTSTART:20261012T221900Z
DTEND:20261012T233900Z
UID:5705440-7346520@zwift-calendar
X-ZWIFT-ESTIMATE-SOURCE:extrapolated
X-ZWIFT-EXPECTED-DURATION-SECONDS:3403
X-ZWIFT-PLANNING-LOWER-SECONDS:2041
X-ZWIFT-PLANNING-UPPER-SECONDS:4765
X-ZWIFT-RESERVED-DURATION-SECONDS:4800
```

## Checks

- Application: 203 tests, including pinned executable force-reference outputs, real FIT decoding, weekly boundaries, gaps/coasting, recovery, collection checkpoints and ICS revisions.
- OpenTofu: initialization, validation, formatting and live plan. The plan replaces the content-addressed release object and updates three Lambda artifact references, sync environment and sync-only cache permission (1 add, 4 changes, 1 destroy). No schedule or service is added.
- Lambda artifact: locked ARM64 build; verified profiles, constants, licenses and FIT decoder are included.
- LocalStack smoke, Ruff, shell checks and Node syntax checks passed.
- Repository pre-push security gates run before publishing the branch.
