# Finish-time estimates

The hourly sync uses published duration first, supported historical medians second,
then a course/power calculation. Turnout filtering and historical finisher arithmetic
are unchanged. No fixed-hour fallback exists. Missing course distance, unsupported
lap configuration, missing rider dimensions or calculation failure leaves a start-only
entry with a reason. UIDs, stars and both subscription URLs are preserved.

## Power evidence

All completed cycling activities are eligible, regardless of ride/race/workout/climb
classification. The rolling window uses completion time. Ages under 7, 14, 21 and
28 days receive weights 1, .75, .5 and .25 respectively; at 28 days they expire.
For each one-minute duration, each activity supplies its highest contiguous average
power, including real zero-power coasting. Timer stop/start events, invalid samples
and timestamp gaps break efforts. The current decoder accepts contiguous one-second
recordings; sparse/smart recordings are not interpolated into invented efforts.
The weighted mean is normalized over activities supporting each duration. A running
minimum makes it non-increasing; interpolation is linear in log duration/log power.

Beyond the longest measured duration, a log/log least-squares fit uses supported
points at least ten minutes long, constraining decline exponent to 0-.5. Fewer than
two qualifying points uses assumed exponent .1 anchored at the last point. No second
fatigue multiplier, stored FTP, zFTP or Racing Score enters this calculation. This is
a recent-effort estimate, not a claim that ordinary training rides measured maximum
fitness. Below the shortest supported duration, power is held and labelled extrapolated.

With no usable positive power, the explicitly assumed **100 W FTP-based default** is
120 W at 5 minutes, 105 W at 20, 100 W at 60, 90 W at 120 and 80 W at 240. It is
held below five minutes, interpolated logarithmically, and extended after four hours
using the final log/log decline. It is not measured fitness.

Collection paginates the authenticated activity inventory to an empty page (even
older records are traversed, so completion does not assume sorting by completion
time). Each invocation permits 20 pages, up to 10 new/changed FIT downloads and
90 seconds including parsing. Offset continuation relocates the previous head anchor
and overlaps the prior page boundary to account for newly inserted rows. Checkpoints
resume next hour; there is no total activity cap. Completed files are not downloaded
again unless their metadata fingerprint changes. Failed downloads remain queued,
ordered by last attempt to prevent starvation. Raw FIT bytes exist only in memory.

`power-state.json` contains derived per-activity curves, completion dates, fingerprints,
pending/retry flags and a scan checkpoint. Only the sync role can access it; the feed
and historical worker cannot. The shared lease fences every checkpoint. Expiry and
weights recalculate each refresh, even without new rides. Upstream failures retain
in-window curves and label estimates degraded; absence is confirmed only after a
complete inventory. Incomplete collection is never represented as confirmed absence.

## Course and physics

`physics.py` ports force equations and rider sizing from
[kjellrg/zwift-bikes at 8a8952f](https://github.com/kjellrg/zwift-bikes/tree/8a8952f3138ad45fb4f0f3bfbf2bcab73f758a44/shared/utils/physics).
This is a **community approximation, not Zwift's official engine**. Baseline equipment
uses that model's generic 8 kg road bike, CdA reference .32 and road-wheel surface
coefficients. Rider CdA uses its Faria regression, with current profile weight and
height (API grams/millimetres converted to kg/cm). It assumes solo riding without
drafting, powerups, braking, group dynamics or equipment upgrades, including for TTs.
The pinned `forces.ts` itself generates reference outputs via
`scripts/zwift-force-reference.mjs`; Python tests compare forces, CdA and speeds.

The compressed offline bundle contains 293 cycling routes and 287 accepted profiles
from [zwift-data at 1025596](https://github.com/andipaetzold/zwift-data/tree/1025596dce5b7b3c076e84c02e85e8ca3ab4acc4).
Profiles originate from its committed Strava distance/elevation streams, sampled at
approximately 25 m. Stream lengths differing from metadata by 10% or more are
rejected; accepted distances are scaled to official route length. This is community
course evidence and can differ from the game. The pinned model's zwiftmap surface
polygons classify each segment; unmapped areas assume tarmac, as in the reference.
The upstream MIT licenses and third-party notices are bundled alongside the data.

Route IDs identify direction, including separately named reverse routes. An explicit
reverse override without a verified reversed profile falls back to totals. Event
lead-in metadata is included once; only routes marked as laps can repeat. Subgroup
distance targets take precedence and truncate the course, including partial final
segments. Lead-in elevation profiles are not available in this bundle, so their
portion uses coarse distance/ascent and is labelled explicitly. Unknown route
continuations and partial courses without profiles disclose missing elevation.

Each slope has gravity, aerodynamic drag, rolling resistance and acceleration;
speed continues across slope/lap boundaries. Heun integration uses an adaptive
startup step and at most one-second steps. Duration is solved against the power
available for that duration by bisection. The model rejects durations above 48 hours.
Climbing and descending remain separate. Coarse estimates add flat travel time and
climbing energy divided by usable power; descent never cancels ascent. Distance-only
estimates explicitly disclose missing elevation.

Regenerate without scraping model websites at runtime:

```sh
node scripts/zwift-model-data.mjs /path/to/pinned/zwift-data /path/to/pinned/zwift-bikes
node scripts/zwift-force-reference.mjs /path/to/pinned/zwift-bikes
```

Both commands reject wrong revisions. Updating pins and inspecting regenerated data
is a deliberate repository change. Lambda artifacts include the bundle and notices.

## Calendar and configuration

Descriptions show central duration, planning range, conservative end, contributing
activity count/date range, power source and course coverage. Public fields omit raw
power, body measurements, activity IDs and FIT URLs. Evidence includes the union of contributing activities and minimum/maximum support
across the duration points used. Sparse evidence means fewer than three supporting
activities at any of those points. Profile-based measured estimates use +/-20%;
extrapolated, sparse, coarse, default or incomplete/degraded estimates use +/-40%.
Historical estimates retain their central median and use +/-20%. Published durations
are exact. These are configurable planning margins, not statistical confidence intervals.
Upper bounds round up to five minutes. Start-only entries have neither end property.

OpenTofu variables `measured_planning_margin`, `wide_planning_margin` and
`default_power_curve` supply `ZWIFT_MEASURED_MARGIN`, `ZWIFT_WIDE_MARGIN` and
`ZWIFT_DEFAULT_POWER_CURVE` (JSON seconds/watts pairs). The default curve label remains
explicitly assumed when configured. Curves require increasing positive durations and
non-increasing positive watts. Defaults require no operator setup or new schedule.

The refresh report includes estimate/course coverage, pending activities, discovery
completeness, confirmed absence, upstream failures, missing courses and calculation
failures. Preview warms private caches under the lease but does not publish calendars
or advance published revisions. Rolling back the Lambda artifact leaves the new
private cache unused; subscription URLs and historical caches are unchanged.
