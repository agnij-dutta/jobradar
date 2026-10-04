# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed
- Sponsorship: hedged sentences ("we aren't able to sponsor visas for every role") no longer read as a refusal, and export-license, executive-sponsor and EEO immigration-status sentences are ignored. 1,040 postings in the 2026-10-04 snapshot were wrongly "no".
- Sponsorship: "Sponsorship available", "Sponsorship: Yes/No" and "open to sponsoring" are recognized.
- Geography: loose words in a description ("international team", "anywhere from 25 customers", a negated or perk "work from anywhere") no longer make a posting worldwide, and an onsite or hybrid job is never worldwide from prose.
- Geography: a time zone in the location field ("Remote, US time zones") is a working-hours note, not a residency rule. `NA` and `APJ` are read as regions.
- Years: "the last 10 years" company history is no longer a requirement; "6+ years overall" and "(10+ total)" count; one-line requirements with "must have" are no longer skipped as headers; "eight-plus years" parses.
- Level codes: the E ladder is monotonic (E3 no longer ranks below E2).
- Sweep: a board whose jobs all fail to parse is an error instead of "ok" with zero postings (which closed its postings), and an unexpected exception in one board no longer aborts the whole sweep.
- Web build: U+2028/U+2029 in posting text are escaped in `jobs.js`.

## [0.1.0] - 2026-10-05

### Added
- Fetcher for public Greenhouse, Ashby and Lever board APIs. Boards are fetched in parallel with per-host limits, and each board ends as ok, empty or error, so an error is never read as "no jobs".
- Adapter registry, so a new ATS is one class.
- Normalized posting schema: eligible regions and exclusions, work mode, sponsorship, minimum and preferred years, level, pay band, stack tags.
- Parsers for geography (location field, description restrictions, ATS country field), sponsorship, years and level codes, pay bands and stack terms.
- SQLite history with first_seen, last_seen and closed_at; idempotent sweeps; raw payload cache with an offline `reparse`.
- `jobradar search` with match reasons, an exclusion summary and `--why-not`; `--new-since` as an opt-in diff view.
- `jobradar stats`, `jobradar probe`, `jobradar build`.
- Static web UI with client-side filters and evidence on hover.
- Seed list of 310 verified boards, plus 336 dead slugs and 28 known name collisions.
