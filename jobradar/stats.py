"""Aggregate numbers over a snapshot (the "tweet numbers")."""

from __future__ import annotations

from collections import Counter

from .parse_geo import eligible, find_places


def compute(snap: dict, home: str = "IN") -> dict:
    """Aggregate numbers over a snapshot, relative to a home country."""
    meta = snap["meta"]
    ps = snap["postings"]
    boards = snap["boards"]
    eng = [p for p in ps if p.get("is_engineering")]

    def remote_block(rows: list[dict]) -> dict:
        rem = [p for p in rows if p.get("remote_mode") == "remote"]
        scope = Counter(p.get("geo_scope") for p in rem)
        restricted = [p for p in rem if p.get("geo_scope") == "restricted"]
        sets = Counter(",".join(p.get("regions") or []) for p in restricted)
        bare_rows = [p for p in rem if not [x for x in find_places(p.get("location_raw") or "") if x.code != "GLOBAL"]]
        literal = [p for p in rows if "remote" in (p.get("location_raw") or "").lower()]
        literal_scope = Counter(p.get("geo_scope") for p in literal)
        bare = Counter(p.get("geo_source") for p in bare_rows)
        open_home = sum(
            1
            for p in rem
            if eligible(
                p.get("regions") or [], p.get("excluded_regions") or [], home, p.get("geo_scope") or "unspecified"
            )
            == "yes"
        )
        return {
            "remote_postings": len(rem),
            "restricted": scope.get("restricted", 0),
            "global": scope.get("global", 0),
            "unspecified": scope.get("unspecified", 0),
            "restricted_only_by_description": sum(
                1 for p in rem if p.get("geo_source") == "description" and p.get("geo_scope") == "restricted"
            ),
            "location_says_remote": {
                "total": len(literal),
                **{k: literal_scope.get(k, 0) for k in ("restricted", "global", "unspecified")},
            },
            "bare_remote_location": {"total": len(bare_rows), "by_source": dict(bare)},
            f"open_to_{home}": open_home,
            "top_restriction_sets": sets.most_common(8),
        }

    plain = [p for p in eng if p.get("plain_title")]
    plain_known = [p for p in plain if p.get("min_years") is not None]
    plain_5 = [p for p in plain_known if p["min_years"] >= 5]
    plain_8 = [p for p in plain_known if p["min_years"] >= 8]
    junior_titled_5 = [p for p in eng if p.get("title_level") in ("junior", "entry") and (p.get("min_years") or 0) >= 5]
    coded = [p for p in eng if p.get("level_code")]

    home_eng = [
        p
        for p in eng
        if eligible(p.get("regions") or [], p.get("excluded_regions") or [], home, p.get("geo_scope")) == "yes"
    ]

    def ex(rows, n=6):
        rows = sorted(rows, key=lambda p: -(p.get("min_years") or 0))
        return [f"{p['company']}: {p['title']} ({p.get('min_years'):g}+ yrs) {p['url']}" for p in rows[:n]]

    status = Counter(b["status"] for b in boards)
    return {
        "run": {"started_at": meta.get("started_at"), "finished_at": meta.get("finished_at")},
        "boards": {
            "total": len(boards),
            "ok": status.get("ok", 0),
            "empty": status.get("empty", 0),
            "error": status.get("error", 0),
            "companies": len({b["slug"] for b in boards if b["status"] != "error"}),
            "errors": [f"{b['board']}: {b.get('error')}" for b in boards if b["status"] == "error"],
        },
        "postings": {
            "total": len(ps),
            "engineering": len(eng),
            "stale": sum(1 for p in ps if p.get("stale")),
            "with_comp_band": sum(1 for p in ps if p.get("comp")),
            "with_min_years": sum(1 for p in ps if p.get("min_years") is not None),
            f"eligible_{home}_all": sum(
                1
                for p in ps
                if eligible(p.get("regions") or [], p.get("excluded_regions") or [], home, p.get("geo_scope")) == "yes"
            ),
            f"eligible_{home}_engineering": len(home_eng),
        },
        "remote_all": remote_block(ps),
        "remote_engineering": remote_block(eng),
        "sponsorship_engineering": dict(Counter(p.get("sponsorship") for p in eng)),
        "levels_engineering": dict(Counter(p.get("level") or "unknown" for p in eng)),
        "level_source_engineering": dict(Counter(p.get("level_source") or "none" for p in eng)),
        "titles": {
            "plain_titled_engineering": len(plain),
            "plain_with_years_stated": len(plain_known),
            "plain_requiring_5plus": len(plain_5),
            "plain_requiring_8plus": len(plain_8),
            "junior_or_entry_titled_requiring_5plus": len(junior_titled_5),
            "with_level_code": len(coded),
            "examples_plain_5plus": ex(plain_5),
        },
    }


def render(st: dict, home: str = "IN") -> str:
    """Human-readable version of `compute`'s output."""
    b, p = st["boards"], st["postings"]
    ra, re_ = st["remote_all"], st["remote_engineering"]
    t = st["titles"]
    lines = [
        f"Sweep {st['run']['started_at']} -> {st['run']['finished_at']}",
        f"Boards: {b['total']} ({b['ok']} ok, {b['empty']} empty, {b['error']} ERROR) across {b['companies']} company slugs",
        f"Postings: {p['total']} total, {p['engineering']} engineering, {p['with_comp_band']} with a comp band, "
        f"{p['with_min_years']} state minimum years",
        f"Open to {home}: {p[f'eligible_{home}_all']} postings, {p[f'eligible_{home}_engineering']} engineering",
        "",
        "'Remote' is a work mode, not a geography:",
        f"  all roles:   {ra['remote_postings']} say Remote -> {ra['restricted']} restricted to named countries/regions, "
        f"{ra['global']} truly global, {ra['unspecified']} never say",
        f"  engineering: {re_['remote_postings']} say Remote -> {re_['restricted']} restricted, {re_['global']} global, "
        f"{re_['unspecified']} never say; {re_['restricted_only_by_description']} restricted only in the description text; "
        f"{re_[f'open_to_{home}']} confirmed open to {home}",
        f"  engineering postings with 'Remote' in the location field: {re_['location_says_remote']['total']} -> "
        f"{re_['location_says_remote']['restricted']} restricted, {re_['location_says_remote']['global']} worldwide, "
        f"{re_['location_says_remote']['unspecified']} never say",
        f"  engineering postings whose location field names no place: {re_['bare_remote_location']['total']} "
        f"(where they actually hire came from: {re_['bare_remote_location']['by_source']})",
        "  most common restriction sets (engineering): "
        + "; ".join(f"{k or '?'} x{v}" for k, v in re_["top_restriction_sets"]),
        "",
        "A job title is not a level:",
        f"  {t['plain_titled_engineering']} engineering roles have a plain title (no senior/staff/junior/level code); "
        f"{t['plain_with_years_stated']} state years; {t['plain_requiring_5plus']} require 5+ years, {t['plain_requiring_8plus']} require 8+",
        f"  {t['junior_or_entry_titled_requiring_5plus']} roles titled junior/entry/associate still ask 5+ years; "
        f"{t['with_level_code']} titles carry a level code (E2/L4/IC3/II)",
    ]
    if t["examples_plain_5plus"]:
        lines.append("  examples:")
        lines += [f"    {x}" for x in t["examples_plain_5plus"]]
    lines += [
        "",
        f"Sponsorship (engineering): {st['sponsorship_engineering']}",
        f"Levels (engineering): {st['levels_engineering']}",
    ]
    if b["errors"]:
        lines += ["", "Board errors (kept previous postings, marked stale):"] + [f"  {e}" for e in b["errors"][:20]]
    return "\n".join(lines)
