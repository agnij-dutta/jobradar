# Changelog

All notable changes to this project are documented here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

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
