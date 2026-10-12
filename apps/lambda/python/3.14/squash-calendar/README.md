# ASC squash calendar

Public `GET /calendars/squash.ics` publishes Tushar Sariya's eight confirmed
Tuesday fixtures from **UPDATED ASC Fall League 2026 Schedule.pdf**, pages 1–2.
`season.json` pins its SHA-256, opponent identities, court numbers and stable
round IDs. All matches are 18:30–19:00 America/St_Johns. No Thursday substitute
fixtures, byes, November 10 break, or unconfirmed December 10 playoffs are added.
The complete season stays in the calendar, including completed matches.

## Data and access

The PDF controls schedule details; Club Locker's team-level 17:30 time does not
replace the individual 18:30 slot. Player IDs are verified against the pinned
team rosters and position 6 on every refresh. A mismatch fails enrichment closed.

Recurring refresh uses unauthenticated public reads at
`https://api.ussquash.com/resources/`:

- `teams/{team}/players`: verify identity; discard contact/membership fields.
- `res/user/{player}/ratings`: sport 3, rating type 1, Universal Squash Rating.
- `leagues/info/{season}`: discover all divisions within five verified ASC
  seasons (fall 2024 through fall 2026).
- `divisions/playerStandings/{division}`: player display names only.
- `divisions/schedule/{division}/`: confirmed scorecards within 731 days.
- `leagues/scorecards/{scorecard}/list`: completed singles results.

These endpoints return complete arrays, not profile-history pagination.
No opponent profile-history or paid match-insights endpoints are queried.
The normal Club Locker web login uses CAPTCHA; unattended login is deliberately
not automated. No password, bearer token, SSM secret, or account-session cookie
is deployed. A one-time signed-in own-profile export of the latest 20 rows adds
seven completed tournament/box matches via `own_history.json`, dated October 12,
2026. Its retirement and duplicate team-league rows are excluded. Older own
non-league matches are not included; this is accessible partial history, not a
complete match record. The seed contains only sporting facts and source URLs.

The shipped public JS client was inspected to identify normal read contracts
(main `main-6FWV5M76.js`, API client `chunk-XT5Q7OU4.js`, profile
`chunk-PVDR2XEE.js`; verified against live responses on October 12, 2026).
**Scorecard** `wid1/oid1` and `wset/oset` are winner/loser oriented: `winner=V`
means that winner represented the visiting team. Confirmed live example:
3974792, Katie Thompson (visiting team 49985) defeated player 237203 from home
team 49982. **Profile** IDs are home/visitor oriented but its score string is
winner-first. Never apply one endpoint's normalization to the other.

Only complete best-of-five squash singles with known players and a consistent
three-game winner enter the model. Doubles, walkovers/defaults, retirements,
abandoned/unknown statuses and incomplete scores are excluded. IDs deduplicate
matches across sources. A fresh scorecard overrides the dated profile export.
Past scorecards are fetched again to pick up corrections. Same-day results are
excluded because team scorecards do not provide reliable match completion times.

## Previews and estimates

Upcoming fixtures contain both current official ratings, own-model whole-percent
win chances, accessible head-to-head, last five completed results for each player,
three recent common opponents where available, source links and data timestamp.
The model is regularized Bradley–Terry (L2 penalty `0.5 * sum(strength²)`, lambda 1),
with exponential match weights of half-life 180 days. It requires five eligible
matches per player and a connected comparison graph; otherwise it displays
“Insufficient accessible history for an estimate.” Official ratings are display
metadata, never retrospective training inputs.

The chronological backtest trains strictly before each date, then scores that
date's supported matches. Brier score and sample count describe accessible data,
not calibrated betting odds. October 12 live check: 1,210 eligible matches,
741 scored holdouts, Brier 0.212. Selection bias and missing non-league results
limit interpretation. No subscription upgrade is needed.

A preview captured before kickoff is frozen when the match starts. Bootstrap does
not invent historical predictions for completed fixtures. A result is attached
only when date, division and both player IDs match exactly. The October 6 Justin
David substitute result cannot be attached to the PDF fixture against Katie.
Changed dates/opponents retain the stable event UID but invalidate the old preview;
removed fixtures become cancellations with increasing SEQUENCE.

## Runtime and operations

The shared calendar infrastructure provisions independent feed/sync Lambdas,
versioned private S3 snapshots, a conditional lease, public API Gateway, failure
queue and alarms. Refresh: daily 03:15 and Tuesday 16:30 Newfoundland time, with
hourly health checks. The feed role has no upstream access credentials or S3 writes.
The additional shared-module schedule input defaults to empty for other calendars.

A failed initial enrichment still publishes all eight PDF fixtures. Later source
failures retain previous enrichment and its original timestamp. After 48 hours,
future-event ratings are marked stale and probabilities suppressed at download
time, even if sync has stopped. A frozen preview already older than 48 hours at
kickoff also stays suppressed. Separate EnrichmentFailure metrics/alarms detect
source errors while schedule publication succeeds. Unexpected internal publication
failures retain the previous atomic snapshot and raise Lambda errors.

Responses have a content ETag, five-minute public cache and an `.ics` attachment
filename. Events are busy (`OPAQUE`), UTC instants preserve Newfoundland DST, and
no alarms are forced on the subscriber. S3 retains 35 days of noncurrent versions.
The endpoint is intentionally public and includes names, fixture times and sports
history summaries. It contains no login credentials or private contact fields.

```sh
uv run --frozen --directory apps/lambda/python/3.14/squash-calendar pytest
uv run --frozen --directory apps/lambda/python/3.14/squash-calendar python -m squash_calendar sync
```

Deploy unit: `aws-staging-squash-calendar`. The normal OpenTofu apply workflow
initializes the snapshot after deployment. To change the PDF fixtures, edit the
manifest preserving round IDs, update source checksum and tests, deploy, then sync.
Add a newly verified season ID explicitly when extending history coverage.
