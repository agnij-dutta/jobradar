"""jobradar command line.

jobradar probe                 verify candidate slugs, write seeds/boards.json + seeds/dead.json
jobradar sweep                 fetch every board, write data/snapshot.json (+ SQLite history)
jobradar reparse               re-run parsers over the saved raw payloads, no network
jobradar search --stack ...    search the FULL current snapshot, with reasons
jobradar stats                 aggregate numbers
jobradar build                 build the static web UI into dist/
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap

from . import search as S
from .parse_level import LEVELS


def _csv(s: str | None) -> list[str]:
    return [x.strip() for x in (s or "").split(",") if x.strip()]


def cmd_probe(a) -> int:
    """Probe candidate slugs and merge the results into the seed files."""
    from . import seeds

    cands = seeds.load_json("candidates.json", [])
    if a.only:
        cands = [c for c in cands if c["slug"] in _csv(a.only)]
    print(f"probing {len(cands)} candidate slugs x 3 ATSs ...", file=sys.stderr)
    r = seeds.probe(cands, workers=a.workers, log=lambda m: print(m, file=sys.stderr))
    if a.dry_run:
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in r.items()}, indent=1))
        return 0
    boards, dead = seeds.merge_probe(seeds.boards(), seeds.load_json("dead.json", []), {c["slug"] for c in cands}, r)
    live = r["live"]
    (seeds.SEEDS / "boards.json").write_text(json.dumps(boards, indent=1, ensure_ascii=False) + "\n")
    (seeds.SEEDS / "dead.json").write_text(json.dumps(dead, indent=1) + "\n")
    (seeds.SEEDS / "probe-review.json").write_text(
        json.dumps({"probed_at": r["probed_at"], "unconfirmed_identity": r["review"], "errors": r["errors"]}, indent=1)
        + "\n"
    )
    print(
        f"boards: {len(boards)} ({len(live)} answered this probe) | dead slugs: {len(dead)} | probe errors: {len(r['errors'])} | "
        f"identity unconfirmed: {len(r['review'])}"
    )
    return 0


def cmd_sweep(a) -> int:
    """Run a full sweep and print the run summary."""
    from . import sweep

    meta = sweep.run(workers=a.workers, log=lambda m: print(m, file=sys.stderr), only=_csv(a.only) or None)
    print(json.dumps(meta, indent=1))
    return 0 if meta["boards_error"] == 0 or not a.fail_on_error else 2


def cmd_reparse(a) -> int:
    """Re-run parsers over saved raw payloads."""
    from . import sweep

    print(json.dumps(sweep.reparse(log=lambda m: print(m, file=sys.stderr)), indent=1))
    return 0


def _load(path: str | None) -> dict:
    from pathlib import Path

    from . import store

    return store.load_snapshot(Path(path) if path else store.SNAPSHOT_PATH)


def _fmt_hit(i: int, h: S.Hit) -> str:
    p = h.posting
    comp = p.get("comp")
    comp_s = ""
    if comp and comp.get("usd_min") is not None:
        comp_s = f" | ~${comp['usd_min'] // 1000}k-{comp['usd_max'] // 1000}k" + (
            "" if comp["currency"] == "USD" else f" ({comp['currency']})"
        )
    yrs = "yrs ?" if p.get("min_years") is None else f"{p['min_years']:g}+ yrs"
    head = (
        f"{i:>3}. [{h.score:>5}] {p['company']} | {p['title']}\n"
        f"       {p.get('remote_mode')} | {', '.join(p.get('regions') or []) or 'geo unspecified'} | "
        f"{yrs} | level {p.get('level') or '?'} | visa {p.get('sponsorship')}{comp_s}\n"
        f"       {p['url']}"
    )
    body = [f"       + {w}" for w in h.why] + [f"       ! {c}" for c in h.caveats]
    return "\n".join([head, *body])


def _posted_before(hits: list[S.Hit], snapshot_at: str | None, days: int) -> int:
    """Count matches whose posted date is more than `days` before the snapshot."""
    if not snapshot_at:
        return 0
    from datetime import datetime, timedelta

    cutoff = (datetime.fromisoformat(snapshot_at) - timedelta(days=days)).isoformat()
    return sum(1 for h in hits if (h.posting.get("posted_at") or "9999") < cutoff)


def cmd_search(a) -> int:
    """Search the snapshot and print results, exclusions and near misses."""
    snap = _load(a.snapshot)
    new_since = a.new_since
    if new_since == "last":
        new_since = snap["meta"].get("previous_run_started_at") or snap["meta"].get("started_at")
    q = S.Query(
        stack=_csv(a.stack),
        region=(a.region or "").upper() or None,
        include_unverified_geo=a.include_unverified,
        max_years=a.max_years,
        strict_years=a.strict_years,
        levels=_csv(a.level),
        remote=a.remote,
        min_comp_usd=a.min_comp,
        require_comp=a.require_comp,
        no_sponsorship_ok=not a.needs_visa,
        engineering_only=not a.all_roles,
        company=a.company,
        title=a.title,
        text=a.text,
        new_since=new_since,
        min_score=a.min_score,
    )
    hits, misses = S.run(snap["postings"], q)
    if a.json:
        out = {
            "query": q.__dict__,
            "total": len(snap["postings"]),
            "matched": len(hits),
            "results": [
                {
                    "score": h.score,
                    "why": h.why,
                    "caveats": h.caveats,
                    **{k: v for k, v in h.posting.items() if k != "description"},
                }
                for h in hits[: a.limit]
            ],
            "excluded_summary": S.summarize_exclusions(misses),
        }
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return 0
    m = snap["meta"]
    print(
        f"Searched ALL {len(snap['postings'])} current postings from {m.get('boards_total')} boards "
        f"(snapshot {m.get('finished_at')}). {len(hits)} match.\n"
    )
    for i, h in enumerate(hits[: a.limit], 1):
        print(_fmt_hit(i, h))
        print()
    if len(hits) > a.limit:
        print(f"... {len(hits) - a.limit} more (use --limit)\n")
    old = _posted_before(hits, m.get("finished_at"), days=30)
    if hits and new_since is None:
        # The point of searching the full set: most good matches are not new.
        print(f"{old} of {len(hits)} matches were first posted more than 30 days before this snapshot.\n")
    print("Excluded (a posting can have several reasons):")
    for label, n in S.summarize_exclusions(misses):
        print(f"  {n:>6}  {label}")
    if a.why_not:
        # The near misses: best stack matches that a filter removed, and why.
        near = [mm for mm in misses if mm.score > 0 and not any("engineering" in r for r in mm.reasons)][: a.why_not]
        if near:
            print("\nBest stack matches you are NOT seeing, and why:")
            for mm in near:
                p = mm.posting
                print(f"  [{mm.score:>5}] {p['company']} | {p['title']} | {p['url']}")
                for r in mm.reasons:
                    print("          - " + textwrap.shorten(r, 140))
    return 0


def cmd_stats(a) -> int:
    """Print aggregate numbers over the snapshot."""
    from . import stats

    snap = _load(a.snapshot)
    st = stats.compute(snap, home=a.home.upper())
    print(json.dumps(st, indent=1) if a.json else stats.render(st, home=a.home.upper()))
    return 0


def cmd_build(a) -> int:
    """Build the static web UI."""
    from . import webbuild

    out = webbuild.build(snapshot_path=a.snapshot, out_dir=a.out)
    print(json.dumps(out, indent=1))
    return 0


def main(argv: list[str] | None = None) -> int:
    """Entry point for the `jobradar` command."""
    ap = argparse.ArgumentParser(prog="jobradar", description="Search company job boards straight from ATS APIs.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("probe", help="verify candidate slugs on Greenhouse/Ashby/Lever")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--only", help="comma-separated slugs")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(fn=cmd_probe)

    p = sub.add_parser("sweep", help="fetch every board and write the snapshot")
    p.add_argument("--workers", type=int, default=12)
    p.add_argument("--only", help="comma-separated slugs")
    p.add_argument("--fail-on-error", action="store_true", help="exit 2 if any board errored")
    p.set_defaults(fn=cmd_sweep)

    p = sub.add_parser("reparse", help="re-run parsers over saved raw payloads (no network)")
    p.set_defaults(fn=cmd_reparse)

    p = sub.add_parser("search", help="search the full current snapshot")
    p.add_argument("--stack", help="comma-separated terms, e.g. typescript,solidity")
    p.add_argument("--region", help="your country (ISO code, e.g. IN); keeps only postings open to it")
    p.add_argument(
        "--include-unverified", action="store_true", help="also keep postings that never say where they hire"
    )
    p.add_argument("--max-years", type=float, help="drop postings requiring more years than this")
    p.add_argument("--strict-years", action="store_true", help="also drop postings that do not state years")
    p.add_argument("--level", help=f"comma-separated levels: {','.join(LEVELS)}")
    p.add_argument("--remote", action="store_true", help="work mode remote only")
    p.add_argument("--min-comp", type=int, help="minimum top-of-band, USD/yr (approx FX)")
    p.add_argument("--require-comp", action="store_true", help="drop postings with no published band")
    p.add_argument("--needs-visa", action="store_true", help="drop postings that say no visa sponsorship")
    p.add_argument("--all-roles", action="store_true", help="include non-engineering roles")
    p.add_argument("--company", help="regex on company/slug")
    p.add_argument("--title", help="regex on title")
    p.add_argument("--text", help="regex on title+description")
    p.add_argument("--new-since", help="'last' (previous sweep) or an ISO timestamp. A view, not the default.")
    p.add_argument("--min-score", type=float, default=0.0)
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--why-not", type=int, default=5, help="show N best stack matches that were filtered out")
    p.add_argument("--snapshot", help="path to snapshot.json")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_search)

    p = sub.add_parser("stats", help="aggregate numbers over the snapshot")
    p.add_argument("--home", default="IN")
    p.add_argument("--snapshot")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_stats)

    p = sub.add_parser("build", help="build the static web UI into dist/")
    p.add_argument("--snapshot")
    p.add_argument("--out", default=None)
    p.set_defaults(fn=cmd_build)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    raise SystemExit(main())
