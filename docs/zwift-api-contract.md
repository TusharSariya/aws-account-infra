# Zwift calendar API contract

Verified read-only against the user's authorized Zwift account on 2026-10-09.
These are observed first-party web/Companion API contracts, not a documented
third-party developer API guarantee. Contract changes fail closed and leave the
last successful calendar available.

- Authentication: `https://secure.zwift.com/auth/realms/zwift/tokens/access/codes`,
  form client `Zwift_Mobile_Link`, password or refresh-token grant. Responses
  include access and refresh tokens plus their expiry seconds.
- API origin: `https://us-or-rly101.zwift.com/api/`, bearer token, JSON accept,
  `Source: zwift-web`, `Zwift-Api-Version: 2.5`.
- `profiles/me` supplies eligibility fields. `scoring/current` and `scoring/max30`
  return `scores.ZWIFT_PUBLIC_SCORE.value`. Account credentials and responses
  containing identifying fields are not fixtures.
- `event-feed?from=<epoch-ms>&limit=50` returns `data[].event` and an opaque
  `cursor`. Continuation requests carry the cursor and limit. A null/empty cursor
  ends the inventory. Limit 200 was rejected. Pages overlap during live inventory
  changes, so event IDs are deduplicated and repeated cursors are rejected.
- A complete live pagination traversed 105 pages and 5,204 unique published events,
  including the requested second week. The public `public/events/upcoming` listing
  stops at 500 despite offset pagination; it is deliberately not a fallback.
  The authenticated feed is enumerated to its terminal cursor, then subgroup
  starts are filtered into the 14-day window. Parent event timestamps are not
  safe stopping boundaries. Pagination is capped at 400 pages; hitting the cap
  or transport budget aborts publication rather than truncating the calendar.
- Events carry `eventType`, `sport`, `accessExpression`, `eventSubgroups`, and
  sometimes `parentId`. Subgroups carry IDs, labels, score-band display text,
  start time, route, distance/laps, timed duration, rules and access restrictions.
  Displayed bands and race-up permissions can differ, so both must match.
  Authenticated subgroups also return `accessValidationResult`; an explicit false
  excludes the group. The observed `accessRules` entry `scored.race` must have a
  true result; unknown entries are excluded.
  A live beginners event had a `0-0` placeholder band; this is excluded.
- `public/events/<id>` resolves recurring parent history.
  `race-results/summary?event_subgroup_id=<id>` returns sampled `firstEntries`
  with qualification/flag status, previous score and activity elapsed milliseconds.
  Only aggregated score/time bins survive extraction. The summary does not
  establish a complete finish distribution, so duration estimates say “sampled”.

The score is read from Zwift's calculation; this service does not invent a score
from watts/kg or assume race history is necessary. Fixtures keep only public
race metadata and synthetic account/score data. No raw authentication, profile,
or identifiable result responses are committed.

## Special rides and unbanded events

The 2026-10-09 authenticated inventory also verified:

- Tour of Watopia `GROUP_RIDE` events have the `tourofwatopia2026` tag and an
  `eventSeries.name` naming the campaign/stage. Their Long/Standard/Short subgroup
  names distinguish route lengths even when `distanceInMeters` is zero. The rider's
  selected route is the shortest eligible subgroup.
- Unrestricted rides/races can have null `accessExpression`, null
  `accessValidationResult`, and empty `accessRules`. Those fields do not constitute
  a failed score lookup. A missing score band is explicitly displayed as unbanded.
- Legacy category-enforced races can use `powerCurves.category` or compound-power
  expressions. For unbanded entries only, an explicit authenticated subgroup
  `accessValidationResult: true` confirms those rules against the current rider.
  False, malformed and unresolved restrictions remain exclusions; Racing Score is
  never converted into a legacy category.
- Some score-band display labels end with ` Max` (for example `0-210 Max`) and
  their access expressions use `scoring.max30`. These remain score-filtered races.

First-party campaign references used for the explicit recognition list:
[Tour of Watopia](https://forums.zwift.com/t/tour-of-watopia-october-2026/671621),
[Tour of Watopia event tag](https://www.zwift.com/eu-de/events/tag/tourofwatopia2026),
[Tour de Zwift](https://forums.zwift.com/t/tour-de-zwift-january-2026/661328),
[Zwift Games](https://forums.zwift.com/t/zwift-games-february-2026/665119), and
[Zwift Big Spin](https://forums.zwift.com/t/the-big-spin-february-2026/666258).
This is a curated list of named campaigns, not automatic discovery of every future
special event or every community-organized series.

At 2026-10-09 16:26 UTC, the expanded filter found 934 entries in the next seven days:
488 score-banded races, 279 unbanded races, and 167 special rides. The following
seven days had 578 entries (302, 108, and 168 respectively). Each special ride used
one shortest eligible route. These are currently published start slots, not a
historical weekly average or a guarantee of the eventual second-week inventory.
An independent ICS parser verified 1,512 unique entries across the two weeks.

## Hourly programme exclusion

The user subsequently excluded both Tour of Watopia rides and races. This is an
explicit campaign preference, not a heuristic that removes any programme whose
published inventory happens to be dense. Campaign recognition still checks names,
series metadata and tags, so renamed stages remain excluded. Other programmes
and recognized campaigns retain their existing eligibility rules.

Applied to the same October 9 snapshot, the next seven days drop from 934 to 601
slots: 322 score-banded races and 279 unbanded races. All 167 special rides in that
week belonged to Tour of Watopia. The 166 Tour of Watopia race slots are also
removed. These are counts from the saved snapshot, not a new live inventory fetch.

The subsequent riding-hours preference keeps starts from 06:00 inclusive to 23:00
exclusive in America/St_Johns, with automatic daylight-saving adjustments. Applied
after the Tour of Watopia exclusion to the same saved snapshot, this removes 60
more first-week slots: 541 remain (297 score-banded, 244 unbanded). The following
week has 211 remaining slots (118 score-banded, 93 unbanded). This is a start-time
filter; events may finish after 23:00.

## Separate subscriptions

The selected inventory is partitioned by presence of a score band into
`/calendars/zwift-banded.ics` and `/calendars/zwift-unbanded.ics`. Both apply the
Newfoundland start window and campaign exclusions before partitioning. Retained
special rides without score bands belong in the unbanded feed. No new eligibility
restriction or time-trial-only filter is introduced by this split.

One hourly upstream extraction produces both feeds in one atomic `current.json`
snapshot. Each calendar has its own name and content ETag; common event/subgroup
UIDs and private revisions survive a move between feeds. The HTTP API routes have
separate exact-path Lambda invocation permissions and share the existing read-only
feed Lambda. Other calendar services retain their single-route defaults.

## Historical discovery (2026-10-09)

Read-only probes using a still-valid cached token confirmed `event-feed?from=`
returns past events: the seven-day probe began October 2 and the ninety-day probe
began July 11. Both returned 50 entries and a continuation cursor. Parent event
5559069 resolved to October 4 and linked to parent 5550688. JSON result requests
must carry `Accept: application/json`; the verified summary response exposes only
`firstEntries` and does not establish complete-result pagination. Backfill uses
these contracts only, resumes cursors, deduplicates identities, and never assumes
parent timestamps are a safe pagination stopping boundary. Cursor expiration
restarts the same scan after a bounded cooldown rather than claiming completion.

## Complete finisher counts (2026-10-11)

Authenticated read-only probes verified
`race-results/entries?event_subgroup_id=<id>&start=<offset>&limit=25`.
For subgroup 7364660, starts 0, 25 and 50 returned 25, 10 and 0 entries,
respectively, with ranks 1-25 then 26-35 and no repeated rider identities.
`limit=2&start=2` returned ranks 3 and 4. The `offset` parameter was ignored;
limits 100 and 1000 returned HTTP 400. The implementation therefore uses only
verified `start`/25-page requests, validates subgroup identities and duplicates,
and requires terminal emptiness. The count includes qualified, unflagged rows
with a positive rank and recorded positive duration. Empty completed results
count as zero; incomplete or failed requests remain unknown. This observed
first-party contract is not an official third-party API guarantee.

Popularity compares complete subgroup counts along recurring-parent chains,
not the sampled duration histogram or event-wide registration totals. Changes
to score bands or legacy pace bounds prevent comparison. Exact Newfoundland
weekday/time matching may leave some DST-shifted international events unknown.

## Activity power and course model (2026-10-12)

The live account contract was checked without publishing personal values:
`profiles/me.weight` is grams and `.height` is millimetres.
`profiles/<id>/activities?start=<offset>&limit=50` returns a list, including
`id`, `sport`, `startDate`, `endDate`, `lastSaveDate`, `fitFileBucket` and
`fitFileKey`. `profiles/<id>/activities/<activity-id>` resolves the current FIT
location. Download uses HTTPS S3 without a Zwift bearer token or redirects.
This agrees with the [upstream client implementation](https://github.com/jsmits/zwift-client/blob/master/zwift/activity.py).
Only completed CYCLING entries inside 28 days contribute; no activity-type limit
is applied. Empty inventory pages establish completion. FIT/download failures are
reported separately from confirmed absence. See the runtime [model notes](../apps/lambda/python/3.14/zwift-calendar/MODEL.md)
for data versions, model sources, assumptions and public/private boundaries.
