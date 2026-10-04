# Contributing to Job Radar

Thanks for helping. The most useful contributions are new companies, new ATS sources, and parser fixes backed by a real posting that got misread.

## Dev setup

```bash
git clone https://github.com/agnij-dutta/jobradar.git
cd jobradar
python3 -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"     # ruff + mypy; the package itself has no dependencies
npm ci                      # Biome, for linting the web UI
```

## Run the checks

```bash
make test        # unit tests (python -m unittest)
make lint        # ruff check, ruff format --check, biome check web
make typecheck   # mypy
make check       # all of the above plus a web build from the sample snapshot (what CI runs)
make format      # apply ruff format and biome format
```

Tests make no network calls. The sample snapshot in `tests/fixtures/sample_snapshot.json` is synthetic.

## Project layout

```
jobradar/
  ats.py               ATS adapters (Greenhouse, Ashby, Lever) and normalize()
  http.py              polite HTTP client: per-host limits, retries, three-state results
  sweep.py             full sweep, raw payload cache, offline reparse
  store.py             SQLite history and the JSON snapshot
  seeds.py             slug probing and identity checks
  parse_geo.py         eligible geography and work mode
  geo_data.py          the gazetteer (countries, regions, states, cities, abbreviations)
  parse_sponsorship.py visa sponsorship
  parse_level.py       minimum years and level
  parse_comp.py        pay bands
  stack.py             stack vocabulary and scoring
  search.py            filters, reasons, exclusion summary
  stats.py             aggregate numbers
  webbuild.py          builds dist/ from the snapshot
  cli.py               the jobradar command
web/                   static UI (index.html, app.js, style.css)
seeds/                 boards.json, candidates.json, dead.json, collisions.json
tests/                 unit tests and fixtures
```

## Add a company

1. Find its board. Open the careers page and look for `boards.greenhouse.io/<slug>`, `job-boards.greenhouse.io/<slug>`, `jobs.ashbyhq.com/<slug>` or `jobs.lever.co/<slug>`.
2. Add an entry to `seeds/candidates.json`:
   ```json
   {"slug": "acme", "category": "devtools", "source": "contrib"}
   ```
3. Probe just that slug: `python3 -m jobradar probe --only acme --dry-run` to check it answers, then run `python3 -m jobradar probe` to rewrite `seeds/boards.json`. A full probe tries every candidate on every ATS and takes a few minutes. Hand-edited `company`, `category` and `note` fields in `boards.json` are kept.
4. Check identity. Generic slugs often belong to a different company with the same name. If the board is the wrong company, add it to `seeds/collisions.json` with a note instead.
5. Run `python3 -m jobradar sweep --only acme` and check a few postings.

## Add an ATS source

1. In `jobradar/ats.py`, subclass `Adapter`:
   - `name`: the ATS id used in board keys (`"workable"`).
   - `fetch_url`: the public endpoint for the full board, with `{slug}`.
   - `probe_url`: the cheapest call that proves the slug exists.
   - `jobs(data)`: return the list of jobs from the response, or `None` if the shape is unexpected. Returning `None` makes the board an error, which is what you want when the API changes.
   - `extract(job)`: return a `RawFields`. Put every location string you have into `locations`. Fill `workplace_type`, `structured_countries` and `comp` only when the ATS really provides them.
2. Register it in `ADAPTERS`.
3. Add a test in `tests/` that runs `normalize()` on a trimmed real job object from that ATS.
4. Public, keyless endpoints only. Don't add anything that needs credentials or scrapes HTML behind a login.

## Fix a parser

Parser bugs are the most valuable reports. Please include the exact location string or requirement sentence.

1. Add a failing test with the real string to `tests/test_geo.py` or `tests/test_level.py`.
2. Fix the parser. Prefer narrow rules, and comment *why* a rule exists.
3. Check you didn't move other results: run `python3 -m jobradar reparse` and then `python3 -m jobradar stats` on your own snapshot, before and after.

## Style

- Python: ruff (`make lint`), mypy clean, type hints on public functions, docstrings on public functions.
- JavaScript: Biome, no framework, no build step.
- Docs and UI copy: plain and specific, no em dashes.
- Commits: short, plain messages describing the change.
