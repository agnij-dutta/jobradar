"""Search over the FULL current snapshot. Diffing is a view, not the search.

Every posting ends up either in `results` (with reasons it matched and any
caveats) or in `excluded` (with every reason it was filtered out), so nothing
disappears silently.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .parse_geo import eligible
from .parse_level import LEVELS, RANK
from .stack import score


@dataclass
class Query:
    stack: list[str] = field(default_factory=list)
    region: str | None = None            # ISO country of the searcher, e.g. IN
    include_unverified_geo: bool = False  # keep "Remote" postings that never say where
    max_years: float | None = None
    strict_years: bool = False           # drop postings that do not state years
    levels: list[str] = field(default_factory=list)
    remote: bool = False
    min_comp_usd: int | None = None
    require_comp: bool = False
    no_sponsorship_ok: bool = True       # False: drop postings that say "no sponsorship"
    engineering_only: bool = True
    company: str | None = None
    title: str | None = None
    text: str | None = None
    new_since: str | None = None         # ISO timestamp; first_seen must be after it
    min_score: float = 0.0


@dataclass
class Hit:
    posting: dict
    score: float
    why: list[str]
    caveats: list[str]


@dataclass
class Miss:
    posting: dict
    score: float
    reasons: list[str]


def _years_str(p: dict) -> str:
    if p.get("min_years") is None:
        return "years not stated" + (f" (prefers {p['preferred_years']:g}+)" if p.get("preferred_years") else "")
    return f"{p['min_years']:g}+ yrs required"


def evaluate(p: dict, q: Query) -> tuple[bool, float, list[str], list[str], list[str]]:
    why: list[str] = []
    caveats: list[str] = []
    reasons: list[str] = []

    if q.engineering_only and not p.get("is_engineering"):
        reasons.append("not an engineering title")
    if q.company and not re.search(q.company, f"{p.get('company')} {p.get('slug')}", re.I):
        reasons.append(f"company does not match /{q.company}/")
    if q.title and not re.search(q.title, p.get("title") or "", re.I):
        reasons.append(f"title does not match /{q.title}/")
    if q.text and not re.search(q.text, f"{p.get('title')}\n{p.get('description')}", re.I):
        reasons.append(f"text does not mention /{q.text}/")

    sc = 0.0
    if q.stack:
        sc, matched, missing = score(p.get("title", ""), p.get("description", ""), q.stack)
        if matched:
            why.append("stack: " + "; ".join(matched))
            if missing:
                caveats.append("no mention of " + ", ".join(missing))
        else:
            reasons.append("description mentions none of: " + ", ".join(q.stack))
        if sc < q.min_score:
            reasons.append(f"stack score {sc} below {q.min_score}")

    if q.region:
        e = eligible(p.get("regions") or [], p.get("excluded_regions") or [], q.region, p.get("geo_scope", "unspecified"))
        where = ", ".join(p.get("regions") or []) or "unspecified"
        if e == "yes":
            why.append(f"open to {q.region} (regions: {where}; from {p.get('geo_source')})")
        elif e == "unknown":
            if q.include_unverified_geo:
                caveats.append(f"posting never says where it hires; {q.region} eligibility unverified")
            else:
                reasons.append(f"{p.get('remote_mode')} but never says where it hires (use --include-unverified)")
        else:
            label = "Remote, but only" if p.get("remote_mode") == "remote" else "located in"
            reasons.append(f"{label} {where}; not open to {q.region}")

    if q.remote and p.get("remote_mode") != "remote":
        reasons.append(f"work mode is {p.get('remote_mode')}, not remote")

    if q.max_years is not None:
        y = p.get("min_years")
        if y is None:
            if q.strict_years:
                reasons.append("years not stated (strict)")
            else:
                caveats.append("years not stated" + (f"; prefers {p['preferred_years']:g}+" if p.get("preferred_years") else ""))
        elif y > q.max_years:
            t = f"requires {y:g}+ years (max {q.max_years:g})"
            if p.get("plain_title"):
                t += "; the title gives no hint"
            reasons.append(t)
        else:
            why.append(f"asks {y:g}+ years")

    if q.levels:
        lvl = p.get("level")
        if lvl is None:
            caveats.append("level unknown")
        elif lvl not in q.levels:
            reasons.append(f"level {lvl} (from {p.get('level_source')}) not in {','.join(q.levels)}")
        else:
            why.append(f"level {lvl} (from {p.get('level_source')})")

    comp = p.get("comp")
    if q.min_comp_usd:
        if not comp or comp.get("usd_max") is None:
            if q.require_comp:
                reasons.append("no comp band published")
            else:
                caveats.append("no comp band published")
        elif comp["usd_max"] < q.min_comp_usd:
            reasons.append(f"comp tops out at ~${comp['usd_max']:,} < ${q.min_comp_usd:,}")
        else:
            why.append(f"comp ~${comp['usd_min']:,}-{comp['usd_max']:,}")
    elif q.require_comp and not comp:
        reasons.append("no comp band published")

    if not q.no_sponsorship_ok and p.get("sponsorship") == "no":
        reasons.append("says no visa sponsorship")

    if q.new_since and (p.get("first_seen") or "") <= q.new_since:
        reasons.append(f"first seen {p.get('first_seen')}, not new since {q.new_since}")

    if p.get("stale"):
        caveats.append("board failed to fetch this run; posting may be closed")

    return (not reasons), sc, why, caveats, reasons


def run(postings: list[dict], q: Query) -> tuple[list[Hit], list[Miss]]:
    hits: list[Hit] = []
    misses: list[Miss] = []
    for p in postings:
        ok, sc, why, cav, reasons = evaluate(p, q)
        if ok:
            hits.append(Hit(p, sc, why, cav))
        else:
            misses.append(Miss(p, sc, reasons))
    hits.sort(key=lambda h: (-h.score, len(h.caveats), h.posting.get("company") or "", h.posting.get("title") or ""))
    misses.sort(key=lambda m: -m.score)
    return hits, misses


_CATS = [
    ("not an engineering title", "not an engineering role"),
    ("company does not", "company filter"),
    ("title does not", "title filter"),
    ("text does not", "text filter"),
    ("description mentions none", "stack: no requested term in the description"),
    ("stack score", "stack score too low"),
    ("but never says where", "geo: says Remote/onsite but never says where"),
    ("Remote, but only", "geo: 'Remote' but restricted to other countries"),
    ("located in", "geo: onsite/hybrid in another country"),
    ("work mode is", "work mode: not remote"),
    ("years not stated", "years: not stated (strict)"),
    ("requires", "years: asks for more than your max"),
    ("level", "level filter"),
    ("comp tops out", "comp: below your minimum"),
    ("no comp band", "comp: none published"),
    ("says no visa", "visa: no sponsorship"),
    ("first seen", "not new since cutoff"),
]


def reason_category(reason: str) -> str:
    for prefix, label in _CATS:
        if prefix in reason[: max(len(prefix) + 40, 60)]:
            return label
    return reason


def summarize_exclusions(misses: list[Miss]) -> list[tuple[str, int]]:
    """Count of postings excluded per reason category (a posting can hit several)."""
    counts: dict[str, int] = {}
    for m in misses:
        for cat in {reason_category(r) for r in m.reasons}:
            counts[cat] = counts.get(cat, 0) + 1
    return sorted(counts.items(), key=lambda kv: -kv[1])


__all__ = ["Query", "Hit", "Miss", "run", "evaluate", "summarize_exclusions", "LEVELS", "RANK"]
