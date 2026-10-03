# iRacing calendar duration evidence

Investigated 2026-10-03 using public official sources and the existing sanitized
authenticated API captures. No live authenticated requests were made.

## The schedule already supplies session blocks

The [cutover record](iracing-api-cutover.md) identifies the API fixtures as captures
from 2026-10-01. Both [active schedules](../apps/lambda/python/3.14/iracing-calendar/tests/fixtures/api/active-seasons.json)
and [archived schedules](../apps/lambda/python/3.14/iracing-calendar/tests/fixtures/api/archived-seasons.json)
contain `race_time_descriptors[].session_minutes`, alongside the exact start times.
Observed examples:

| Event | Race limit | Session minutes | Calendar block |
| --- | --- | --- | --- |
| Creventic Mugello | 720 minutes | 751 | 12 h 31 min |
| Bathurst 12 Hour | 720 minutes | 761 | 12 h 41 min |
| Bathurst 1000 | 161 laps | 399 | 6 h 39 min |
| Suzuka 1000km | 173 laps | 427 | 7 h 7 min |
| Indy 500 | 200 laps | 308 | 5 h 8 min |
| IMSA Classic 500 | 139 laps and 1440 minutes | 1481 | 24 h 41 min |

`race_time_limit` is in minutes in these captures: Bathurst 12 Hour is 720 and
Daytona 24 is 1440, matching the [official event descriptions](https://www.iracing.com/special-events/).
The archived Bathurst 12 Hour has `event_sessions` containing 30-minute practice,
8-minute qualifying and 720-minute race. Its descriptor is 761 minutes, three more
than that sum. Other timed specials show the same three-minute difference. The
captured fields establish these values; the purpose of the extra three minutes
is not documented here and must not be asserted as fact.

Using `session_minutes` as the full scheduled calendar block is an inference from
the field name, its placement alongside the starts, and the observed values. The
[captured endpoint documentation](../apps/lambda/python/3.14/iracing-calendar/tests/fixtures/api/documentation.json)
does not define its response semantics or promise an exact finish. No public
official schema definition was found during this investigation.

For lap-only races, this value is clearly a planning duration rather than a known
actual finish. A mixed lap/time race can instead expose a large configured cap:
IMSA Classic 500 publishes 139 laps, a 1440-minute race limit and a 1481-minute
session block. Do not describe that block as a realistic lap-derived estimate.

## Attached sessions and distance events

The [official Bathurst 1000 announcement](https://www.iracing.com/this-week-iracing-bathurst-1000-presented-by-next-level-racing-special-event/)
confirms 161 laps, a 30-minute warmup, and an eight-minute qualifying session.
This independently supports accounting for attached sessions after the published
session start. Registration opens earlier and is separate from these sessions.
Distance-branded races already have explicit lap limits in the captured API:
Bathurst 1000 has 161, Suzuka 1000km has 173, and Portimao 1000km has 215. Prefer
those limits to converting a title's nominal distance using rounded track length.

`event_sessions[].minutes` must be read with `unlimited_time`: the archived Indy
500 race has `minutes: 10080` and `unlimited_time: true`. That number is not a
seven-day race duration. Likewise, `laps: 32767` with `unlimited_laps: true` is
not an actual race lap limit. Evidence: the archived schedule capture linked above.

## Official lap-time estimates exist, but in telemetry

iRacing documents `CarClassEstLapTime` and `DriverCarEstLapTime` as simulator
telemetry session strings containing estimated lap times in its
[2021 Season 2 Patch 2 release notes](https://support.iracing.com/support/solutions/articles/31000159881-2021-season-2-patch-2-release-notes-2021-03-26-02-).
This establishes an official estimate in that interface, not availability to this
server-side calendar. Neither those values nor a documented web API lap-time
lookup appears in the captured schedule contract. A formula such as
`laps * representative_lap_time` therefore needs an additional verified input;
the formula alone cannot produce an evidence-backed duration here.

## Recommended implementation

Use the positive finite `session_minutes` from the descriptor that supplied each
start as the calendar block, including for lap/distance events. Do not add
practice or qualifying again. Describe these as iRacing scheduled session blocks,
with estimated finishes for lap-based races; distinguish a configured cap from a
race-time estimate when both lap and time limits are present.

If a descriptor lacks a usable duration, a positive finite race time limit can
support a fallback. Add only available, finite attached session durations, respecting
unlimited flags, and disclose incomplete overhead. Without either an API session
block or verified race duration/lap-time inputs, retain an explicitly unknown
duration rather than inventing pace. Keep date-only events date-only.

The documented `season/race_guide` endpoint only covers starts within three hours
of a requested time and rewrites past times to the present. It is unsuitable for
historical validation, and this investigation did not inspect its response shape.
Source: captured endpoint documentation linked above.
