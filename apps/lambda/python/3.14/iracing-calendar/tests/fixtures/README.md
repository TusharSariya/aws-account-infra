# Public-source fixtures

`weekly.html` is a reduced fixture for the official September 22-28, 2026 weekly
post: https://www.iracing.com/this-week-in-iracing-september-22nd-to-september-28th-2026/
It retains both setup schedules to test exact UTC start extraction and coverage.
The remaining fixtures in tests are synthetic and deliberately include alternating
weeks, midnight UTC starts, lap-based lengths and date-only placeholders.
# Special-event inventory fixture

`special-events-2026.html` is a reduced capture of the official special-events page.
It retains the observed title/card selectors, inline date markup, car summaries,
and official detail links. Images, scripts, tracking and descriptive prose were
removed. It contains all 33 published entries (30 paved and 3 dirt/off-road),
including the undated charity event. This is public-page evidence, not an
authenticated API fixture. The catalog's API mappings remain unresolved.

`api/indianapolis-2026.json` is a minimized, public-field-only capture of the
2026-10-09 authenticated active-season response. Season 6626 / series 635
confirms the catalog's 8 Hours of Indianapolis: October 16-18, road track 448,
open setup, 480 racing minutes, and five published session starts. No account
identifiers, credentials, or signed download URLs are included.
