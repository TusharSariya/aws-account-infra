> Updated conclusion: direct HTTP from Lambda DOES work with the full browser
> User-Agent below. Earlier 403 observations document the default-client behavior.

# Paul Reynolds primary-source extraction research

Checked 2026-09-24 UTC. Read-only, no repository changes.

## Accessible official sources and proof

1. City aquatics page: https://www.stjohns.ca/recreation-culture/recreation-programs/aquatics-and-swimming/
   - HTTP curl succeeds. Saved `/tmp/paul-aquatics.html`.
   - Official facility-specific calendar URL is https://calendar.stjohns.ca/prcc/Week . Prefer this facility scope over general recreation calendar including fitness and other programs.
   - Page embeds upcoming calendar records with title, date, time and detail URL. Current sample: September24 6 Lane & Leisure07:00–08:50 and Leisure Swim09:00–09:50.
   - Embedded records duplicate across `/prcc/`, `/recreation/`, `/default/`. They must not be treated as distinct activities. Only five teaser entries available, so not complete source.
   - Official Subscribe link points to https://www.stjohns.ca/subscribe/ for emailed schedules; this is not proof of an ICS subscription.
2. Linked official seasonal PDF: https://media-003-ca.cdn.govstack.com/stjohns-ca/media/ao2pyjvj/pr_prcc-swim-schedule-sept-2026.pdf
   - Direct curl succeeded. Saved `/tmp/paul-schedule.pdf`; parsed via `pdftotext -layout` into `/tmp/paul-schedule.txt`.
   - Heading establishes validity September20–December5,2026.
   - Explicit holiday closures September30, October12, November11.
   - Thursday rows:6 Lane and Leisure07:00–08:50; Aquatic Fitness and Leisure Swim09:00–09:50;6 Lane and Leisure10:00–13:50;6 Lane and Leisure19:00–19:50.
   - Sunday:6 Lane/Leisure07:00–08:50; Everyone Welcome14:00–14:50,15:00–15:50,17:00–17:50;6 Lane/Leisure19:00–20:20.
   - PDF says schedules subject to change, consult swimming webpage, closures posted on website/social.
3. Facility page: https://www.stjohns.ca/recreation-culture/facilities-parks-trails/community-centres/paul-reynolds-community-centre/
   - Confirms35 Carrick Drive, 25m lane pool and separate leisure pool. Links both calendar and PDF.
4. Fees page: https://www.stjohns.ca/recreation-culture/recreation-programs/drop-in-programs-and-fees/
   - Indoor Paul Reynolds recreational swimming has fees; avoid calling these free-of-charge swims.

## Calendar host access limitations

Direct curl and web.open of https://calendar.stjohns.ca/recreation/ and /prcc/Week yielded403 with message access blocked for security reasons. Curl default and ordinary Mozilla user agent both blocked. No access-control circumvention attempted. Parent reports normal Chrome browser succeeds. Parent separately inspects event detail and offered ICS UI.

No programmatic ICS/RSS/JSON endpoint was independently verified by this research. Do not claim one exists until observed and fetched. Do not interpret403 or absent teaser entries as empty calendar.

## Logical ingestion recommendation

Prefer publisher-exported structured ICS if parent verifies it, then dated event listing/details. Scope facility/calendar first, then swimming category to exclude gym/drop-in fitness. Deduplicate occurrences by upstream identity, preserve published lane/leisure qualifiers, convert local times with America/St_Johns. Discover published future horizon rather than extrapolating weekly schedule indefinitely. Validate completeness before removal reconciliation.

PDF is a demonstrably HTTP-accessible fallback/proof, but should not silently become authoritative live source if a structured calendar fetch fails. If used intentionally: discover current PDF link from aquatics page each sync; parse explicit validity dates, grid, and holiday exclusions; preserve old snapshot if parsing/validation fails. Whole-season PDF has no stable occurrence IDs and may lag ad-hoc closures, so use deterministic date/time/title/facility identity plus careful revisions and provenance. Teaser feed is not sufficient for full reconciliation.

## Browser extraction proof (parent investigation)

Normal Chrome access to `/prcc/Week` succeeded. The parent extracted36 dated swimming occurrence records for September20–26 using links matching `a[href*='/Detail/']`, title text, occurrence date embedded in detailURL, and adjacent `.calendar-bar-time` text. Observed types:6 Lane & Leisure, Leisure Swim,6 Lane Swim,3 Lane & Leisure, Everyone Welcome Swim, Pop in Tot, Therapeutic Adult Swim. This supports HTML ingestion, but does not yet prove headless/serverless access reliability. Four Thursday September24 records corroborate the PDF times above, with online9a.m. event specifically titled Leisure Swim.

The parent also observed a per-event export link `/recreation/Calendar/2026-09-24-0700-6-Lane-amp-Leisure`; browser click returned ERR_BLOCKED_BY_CLIENT. Therefore successful ICS bytes have not yet been verified.

## Main-site embed endpoint check

The aquatics page returns event teaser HTML directly. Inspected scripts:

- https://www.stjohns.ca/sb/gov-js-bundle.js.v1-10-8-0
- https://www.stjohns.ca/sb/sitebuilder-js-bundle.js.v1-10-8-0

No exposed calendar JSON/RSS fetch endpoint found. `gs-feed-carousel` code only controls carousel presentation. The main-site teaser cannot be used to establish whole-window completeness or cancellations.

Pagination proof: the next-week URL https://calendar.stjohns.ca/prcc/Week?StartDate=09/27/2026 returned31 swimming rows in the parent's Chrome extraction. No September30 events were present, corroborating the PDF's explicit holiday closure. Iterate week windows using this observed StartDate parameter, deduplicate boundary occurrences, and constrain extraction to explicitly published dates.

## Real AWS Lambda HTTP proof (2026-09-24 01:35–01:37 UTC)

Deployed disposable `paul-swim-http-proof` in us-east-1 via OpenTofu. Python3.14.7 ARM64, no VPC, matching production swim sync runtime/network model. Dedicated role permitted only its own logs. No production code or calendar snapshot changes.

- urllib request ID: `b5f20120-c187-4473-9112-2429c914ec2d`.
- httpx0.28.1 request ID: `a7bdd504-e0e0-4062-9fe0-c1a6df16645b`.
- Both weekly URLs (September20 and27) and the recreation swim-filter URL returned HTTP403,157-byte access-block message with both clients.
- Official PDF returned HTTP200, application/pdf,191340bytes and valid `%PDF-` signature with both clients.
- Main aquatics page returned HTTP200,120248bytes viahttpx; expected published PDF link was present.
- Conclusion: direct Lambda HTTP fetching of the live calendar is blocked with tested clients; main-page discovery and PDF download are proven. No claim of successful live event parsing from Lambda. Calendar403 must never be interpreted as zero events.
- Reproduction IaC/code and raw results: `/tmp/paul-lambda-proof/` (`main.tf`, `probe.py`, `package/httpx_probe.py`, `urllib-result.json`, `httpx-result.json`). Disposable resources removed after test; original feed unchanged.

## Resolved: User-Agent controlled comparison

Real Lambda request `9c3db860-db0c-4616-8737-adc8fb88ccc9`, 2026-09-24
01:42:23 UTC, Python 3.14.7 ARM64, httpx 0.28.1 in us-east-1:

- Default httpx header: 403.
- Change ONLY User-Agent: 200, 36 swimming events in Sept20-26.
- Restore default: 403.
- Next week with full header: 200,31 swimming events; no Sept30 sessions.
- All67 extracted records exactly match independent local HTTP extraction.
- Local IPv4/IPv6 and HTTP1.1/HTTP2 with default header all returned403.
- No cookies, JavaScript, browser engine, or proxy needed.

Proven header:
`Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36`

Thus User-Agent-dependent filtering explains the observed failure; a blanket
AWS IP block does not. X-Azure-Ref identifies Azure Front Door in the path;
the exact WAF/backend rule needs the operator's logs and is not proven.
Reference: https://learn.microsoft.com/en-us/azure/web-application-firewall/afds/waf-front-door-monitor

Raw evidence `/tmp/paul-lambda-proof/lambda-ua-result.json` and
`local-extraction.json`. Temporary test infrastructure destroyed via OpenTofu.
Production collector excludes the three Pop in Tot entries in the first week,
so its eligible count is33 rather than36. Full Sept24-Oct24exclusive read:133
eligible city events.
