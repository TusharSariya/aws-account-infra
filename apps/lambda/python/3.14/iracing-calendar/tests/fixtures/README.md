# Special-event inventory fixture

`special-events-2026.html` is a reduced capture of the official special-events page.
It retains the observed title/card selectors, inline date markup, car summaries,
and official detail links. Images, scripts, tracking and descriptive prose were
removed. It contains all 33 published entries (30 paved and 3 dirt/off-road),
including the undated charity event. This is public-page evidence, not an
authenticated API fixture. Reviewed API mappings are stored separately in the catalog. The fixture retains
the historical SFL Mountain Showdown label to exercise explicit alias compatibility.

`api/indianapolis-2026.json` is a minimized, public-field-only capture of the
2026-10-09 authenticated active-season response. Season 6626 / series 635
confirms the catalog's 8 Hours of Indianapolis: October 16-18, road track 448,
open setup, 480 racing minutes, and five published session starts. No account
identifiers, credentials, or signed download URLs are included.

The additional `iRacing Indy 8 Hour` alias was reviewed against the official
[October 12 announcement](https://www.iracing.com/this-week-iracing-indy-8-hour-presented-by-pcs-by-thomas-special-event/).
Its five October 16-18 starts exactly match the deployed API schedule for season
6626, series 635. The historical catalog display name remains independent.
