# iRacing API cutover evidence

Authenticated contract captured 2026-10-01 from `/data/doc`, `/data/series/seasons`,
`/data/series/stats_series`, and `/data/series/season_schedule`. Fixtures contain only
public schedule fields; account eligibility, credentials, and signed download URLs
are removed. Download host observed: `scorpio-assets.s3.us-east-1.amazonaws.com`.

The API publishes explicit `race_time_descriptors.session_times` in UTC and repeating
rules with round-scoped start dates/day offsets. `week_end_time` is inclusive: some
specials publish their last session exactly at that boundary. The adapter never uses
`weather.simulated_start_time`. Recurrences with unobserved local-timezone semantics
fail closed until a real contract is captured. Current irregular races use explicit
UTC starts, including their DST changes.

## Reviewed snapshot comparison

Baseline contained 445 events across 136 distinct rounds. All 136 rounds have reviewed
identity mappings. The preview contains 558 events: 551 timed and seven date-only.
There are 124 additions, 11 removals and 42 start changes. Every removal is outside
the 30-day retention window. Of the changes, 35 turn date-only placeholders into
confirmed starts; seven correct already timed starts. No unexpected identity removals
or duplicate `(API round identity, start)` pairs remain.

The seven corrections concern series 229, 574 and 575 for September 22-28. The official
weekly article differs from the API by one hour. Actual completed-race records from
`/data/results/search_series` confirm **every** API start. Sanitized timestamp evidence
is in `tests/fixtures/api/completed-starts.json`; reviewed before/after pairs are in
`catalogs/migration.json`. This resolves the conflict using observed completed races,
not an assumed DST rule.

Representative checks:

- September Bristol: both NASCAR iRacing variants publish 250 laps, not Bristol 500.
- Daytona 500: only round zero matches; the official date window also overlaps the
  next Fixed round, demonstrating why dates alone are insufficient.
- Bathurst 1000: AU and US series publish five distinct starts. The official 2026
  announcement lists exactly the same five times; both variants remain separate.
- Petit Le Mans: five September starts, never its simulated October 3 10:55 time.
- Indy 500: separate Open/Fixed series and dates verified from archived API schedules.
- INDYCAR road rounds: full-length tour classification supported by the official
  June 30-July 6 weekly description, distinct from specials.

The eight not-yet-published API catalog entries remain reported; seven have confirmed
all-day dates. The charity event is undated and omitted. Future standalone API races
without reviewed mappings block publication for review. No favorites are used.

## Rollback references

Before cutover, production sync code SHA-256 (hex):
`00550dd92b1dbd80f69e83c8fac3537e19555b3be10539e9094ff0ed5695385d`.
The prior artifact remains at the matching content-addressed
`stable/iracing-calendar/<sha256>.zip` release key.

Snapshot bucket: `iracing-calendar-992382747916-us-east-1`.
Prior `current.json` version: `8pEw2cZnjruOy2Z_ovuVrwI5KeToYsDd`.
The preview does not publish the feed. Local review artifacts were generated at
`/tmp/iracing-api-preview.ics`, `/tmp/iracing-api-preview.json` and
`/tmp/iracing-api-preview-report.json`.

Rollback restores the prior application configuration via CI and the reviewed prior
snapshot version under the lease. Preserve current token state: never roll token
secrets back with the feed. Snapshot versions expire after 35 days; release artifacts
remain content-addressed in the existing release bucket.
