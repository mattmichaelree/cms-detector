# campaign fixtures

## trtl_endorsements.html — REAL

`https://texasrighttolifepac.com/endorsements/`, fetched 2026-08-26, HTTP 200,
496 KB. The 2026 endorsement roll. The page renders from a county-keyed JSON
blob embedded in a `<script>` (`const data = {...}`), which is what
`parse_endorsements()` reads. Per the audit, the live page shows the **current
cycle only** — prior cycles vanish, so this capture is the only record of the
2026 roll that will exist once the page turns over.

## cdx_*_SYNTHETIC.json — SYNTHETIC, and labelled so in every filename

**`web.archive.org` is unreachable from this build environment.** Both the
HTTPS and HTTP endpoints are refused before leaving the network:

```
$ curl -sS -D - "http://web.archive.org/cdx/search/cdx?url=jamestalarico.com&matchType=domain&output=json&limit=3"
HTTP/1.1 403 Forbidden
x-block-reason: hostname_blocked
Blocked by egress policy
$ curl -sS "https://web.archive.org/cdx/..."
curl: (35) Recv failure: Connection reset by peer
```

So no real CDX payload could be captured here. These three files are
hand-generated in the **exact wire shape** of `output=json` (a header row
naming the 7 default fields, then one row per capture) and are shaped after
the three lifecycle histories the audit verified live in Aug 2026. They exist
to exercise `parse_cdx()` and `classify_decay()`; they are **not evidence**
about these domains, and no test in this repo cites them as such. The live
test (`test_campaign_live_smoke`) reports which path actually ran, and
`cdx_reachable()` records the refusal reason verbatim rather than treating an
unreachable API as an empty history.

| file | audit finding it is modelled on | classifier verdict |
|---|---|---|
| `cdx_jamestalarico_SYNTHETIC.json` | continuing candidate, full captures every year 2017→2026 | `active` |
| `cdx_beverlypowell_SYNTHETIC.json` | last full capture the day she ended her campaign (2022-04-06); every later capture a redirect; live domain now HugeDomains | `parked` (with a reseller redirect target) |
| `cdx_averieforall_SYNTHETIC.json` | HD112 2024 loser; captures continued ~5 months past the loss, then 404s from mid-2025 | `orphaned` truncated at 2025-04, `dead` in full |

Replace any of these with a real CDX payload the moment an environment with
egress to `web.archive.org` is available; `parse_cdx()` reads the field order
from the header row, so a real payload with extra columns drops straight in.
