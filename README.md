# Job Radar

Search company job boards straight from the ATS APIs (Greenhouse, Ashby, Lever), with filters that read the requirements instead of trusting the title.

No accounts, no keys, no scraping of aggregators. Every company board in `seeds/boards.json` is fetched in full from its public JSON endpoint, normalized into one schema, and searched as a whole.

## Why this exists

Three things that went wrong in a real job search, and what Job Radar does about each.

**1. A diff is not a search.**
A daily sweep script printed only the postings that were new since the last run. When everything was finally pulled from scratch and filtered properly, the best stack match of the whole search had been live for weeks. It never showed up because it was never new on a day the script ran.
Job Radar always searches the full current set. "New since last sweep" exists, but it is a view you opt into, never the default.

**2. "Remote" is a work mode, not a geography.**
A "Remote" role at a card company turned out to be open only to the US, Canada (Ontario or BC only), the Netherlands, Poland and Czechia, with no visa sponsorship. Most "Remote" engineering roles are Remote-US or Remote-EMEA.
Job Radar parses eligible geography as its own field (countries and regions, plus exclusions) from the location field *and* the description text, keeps work mode separate, and pulls out a sponsorship flag.

**3. A job title is not a level.**
A plainly titled "Software Engineer, Internal Systems" asked for 8+ years. A role titled "Backend Engineer E2" was the real fit.
Job Radar reads minimum years from the requirements text ("5+ years", "3-5 yrs", "at least four years", degree-or-experience alternatives, nice-to-have sections kept separate) and level codes (E2, L4, IC3, Engineer II), and only falls back to title words last.

## First full sweep (2026-10-04)

- 310 boards across 283 company slugs (89 crypto, 78 fintech, 73 devtools, 68 AI), 264 with openings, 46 empty, 0 errors. 336 candidate slugs were dead on all three ATSs; 29 resolved to an unrelated company with the same name.
- 17,468 postings, 5,785 engineering. Two back-to-back sweeps: 0 new, 0 closed (idempotent).
- Engineering postings whose location field says "Remote": 996. Of those, 950 (95%) are restricted to named countries or regions. 20 are open worldwide.
- Engineering roles with a plain title (no senior, staff, junior or level code) that state years: 1,001. 513 of them (51%) require 5+ years. Plain "Software Engineer, ..." titles: 174 of 347 require 5+.
- `--stack typescript,solidity --region IN --max-years 3 --remote` returns 23 roles. All 23 were first posted more than 30 days before the sweep. A "new since yesterday" diff would have shown none of them.

## Quick start

Python 3.10+, standard library only.

```bash
python3 -m jobradar sweep            # fetch every board (polite, parallel), write data/snapshot.json
python3 -m jobradar search --stack "typescript,solidity" --region IN --max-years 3 --remote
python3 -m jobradar stats            # aggregate numbers over the snapshot
python3 -m jobradar build            # static web UI into dist/
python3 -m http.server 8787 -d dist  # or just open dist/index.html
```

`pip install -e .` gives you a `jobradar` command instead of `python3 -m jobradar`.

### Search

```
jobradar search --stack "typescript,solidity" --region IN --max-years 3 --remote
```

| flag | meaning |
|---|---|
| `--stack a,b` | score the full description for these terms (aliases: ts, golang, k8s, ...) |
| `--region IN` | only postings open to someone living in this country (ISO code). Region words resolve: APAC includes IN, EMEA does not |
| `--include-unverified` | also keep postings that never say where they hire (shown with a caveat) |
| `--max-years N` | drop postings whose *required* minimum years exceed N. Postings that do not say are kept with a caveat; `--strict-years` drops them |
| `--level entry,junior,mid` | ladder: intern, entry, junior, mid, senior, staff, principal, management |
| `--remote` | work mode remote only |
| `--min-comp 120000` | top of published band, USD/yr (approximate FX); `--require-comp` drops postings without a band |
| `--needs-visa` | drop postings that say no sponsorship |
| `--all-roles` | include non-engineering roles |
| `--new-since last` | the diff view: only postings first seen after the previous sweep |
| `--why-not 5` | show the best stack matches a filter removed, and which filter |
| `--json` | machine-readable output |

Every result says why it matched; every excluded posting carries the reasons it was excluded, summarized at the bottom. Nothing disappears silently.

### Web UI

`jobradar build` writes `dist/` with a single-page client-side filter over a slim copy of the snapshot (descriptions dropped, stack-term counts kept). Filters: country you can work from, work mode, max years, level, minimum pay, stack keywords, visa, engineering only, title/company. Badges show their evidence on hover. "New since last sweep" is a checkbox, off by default.

## How it works

```
seeds/boards.json -> fetch (3-state) -> raw payload (data/raw) -> normalize + parse -> SQLite history -> snapshot.json -> search / stats / web
```

- **Fetcher** (`jobradar/http.py`, `jobradar/sweep.py`): all boards in parallel, at most 3 concurrent requests per ATS host, 250 ms spacing per host, retries with backoff on 429/5xx, `Retry-After` honoured. Each board ends in exactly one state: `ok`, `empty`, or `error`. A board that errors keeps its previously known postings (marked stale); an error is never read as "no jobs". A verified board that starts returning 404 is an error, not an empty board.
- **Raw layer**: the last good payload per board is kept gzipped in `data/raw/`, so `jobradar reparse` can re-run every parser without touching the network.
- **History** (`jobradar/store.py`): SQLite tracks `first_seen`, `last_seen`, `closed_at` per posting. Re-running a sweep is idempotent.
- **Schema** per posting: company, title, url, team, location_raw, remote_mode (onsite/hybrid/remote/unknown), regions, excluded_regions, geo_scope (global/restricted/unspecified), geo_source, sponsorship (yes/no/unknown) with evidence, min_years, preferred_years, level, level_source, title_level, level_code, plain_title, comp band (currency, min, max, interval, approx USD, source), posted/updated dates, stack tags, description text.
- **Parsers**: `parse_geo.py` (gazetteer of countries, regions, US states, Canadian provinces, Indian states, city names and the abbreviations boards actually use: SF, NYC, SEA, US-REM), `parse_level.py` (years and ladder codes), `parse_comp.py` (Ashby/Lever structured bands first, description text second), `stack.py` (term regexes that know Go the language from "go to market").

### Seeds

`seeds/candidates.json` is the list of slugs to try. `jobradar probe` checks each slug on all three ATSs and writes:

- `seeds/boards.json`: boards that answered, with company name and category (crypto, fintech, ai, devtools).
- `seeds/dead.json`: slugs that 404 on every ATS.
- `seeds/collisions.json`: slugs that resolve to an unrelated company with the same name (Safe Software instead of Safe, circle.so instead of Circle, a pizza app called Slice). Kept out of the sweep.
- `seeds/probe-review.json`: boards whose identity could not be confirmed automatically.

## Tests

```bash
make check     # unit tests + JS syntax check
```

The parser tests use real location strings seen on boards ("SF, SEA, NYC, CHI, ATL", "Canada Wide - Excluding Quebec (remote)", "Remote Global (US, EU)", "Worldwide, but must be willing to attend regular EST meetings") and real requirement phrasings.

## Limits

- Parsing is heuristic. Badges show the sentence they came from so you can check.
- Level codes mean different things at different companies; required years beat codes, codes beat title words.
- USD conversion uses fixed approximate rates.
- Greenhouse list endpoints do not expose structured pay, so Greenhouse bands come from description text only.
- Only Greenhouse, Ashby and Lever for now.

## License

MIT
