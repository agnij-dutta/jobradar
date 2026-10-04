"""Eligible-geography, remote-mode and visa-sponsorship parsing.

"Remote" is a work mode, not a geography. This module keeps them separate:

  remote_mode     onsite | hybrid | remote | unknown
  regions         normalized codes the posting is open to (ISO countries + region words)
  excluded        codes explicitly carved out ("Canada, excluding Quebec" keeps CA but
                  records the exclusion; country-level carve-outs land here)
  geo_scope       global | restricted | unspecified
  sponsorship     yes | no | unknown

Sources, in order of trust: the location field(s), restriction sentences in the
description ("open to candidates in ..."), and finally the ATS's structured
country field, which is only used when nothing else says anything.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import geo_data as G
from .parse_sponsorship import parse_sponsorship
from .textutil import normalize_dashes, sentences

# ---------------------------------------------------------------- matchers --

_ALIAS: dict[str, tuple[str, str]] = {}  # alias -> (code, kind)


def _add(alias: str, code: str, kind: str) -> None:
    _ALIAS.setdefault(alias.lower(), (code, kind))


for _code, _names in G.REGIONS.items():
    for _n in _names:
        _add(_n, _code, "region")
for _code, _names in G.COUNTRIES.items():
    for _n in _names:
        _add(_n, _code, "country")
for _code, _names in G.CITIES.items():
    for _n in _names:
        _add(_n, _code, "city")
for _code, _names in G.SUBDIVISIONS.items():
    for _n in _names:
        _add(_n, _code, "subdivision")
for _st, _name in G.US_STATES.items():
    _add(_name, "US", "subdivision")
# Singapore / Hong Kong are city-states; aliases already present as countries.

_CI_RE = re.compile(
    r"(?<![\w])(" + "|".join(re.escape(a) for a in sorted(_ALIAS, key=len, reverse=True)) + r")(?![\w])",
    re.I,
)
_CASED_RE = re.compile(r"(?<![A-Za-z])([A-Z]{2,5})(?![A-Za-z])")
_CA_PROVINCES = {"ON", "BC", "QC", "AB", "MB", "NS", "SK"}

_EXCLUDE_KW = re.compile(r"\b(excluding|except(?: for)?|excl\.?|not including|other than|outside of)\b", re.I)


@dataclass
class Place:
    """One geographic mention found in text."""

    start: int
    end: int
    code: str
    kind: str  # country | region | city | subdivision
    text: str


def find_places(text: str, short_codes: bool = True) -> list[Place]:
    """Find geographic mentions. short_codes enables 2-3 letter upper-case tokens
    (SF, NYC, CA, BC) which are reliable in location fields but noisy in prose."""
    text = normalize_dashes(text)
    out: list[Place] = []
    taken: list[tuple[int, int]] = []
    for m in _CI_RE.finditer(text):
        alias = m.group(1).lower()
        code, kind = _ALIAS[alias]
        # "america" alone is fine, but skip lower-case "us"-style false hits (none here).
        out.append(Place(m.start(1), m.end(1), code, kind, m.group(1)))
        taken.append((m.start(1), m.end(1)))

    def overlaps(a: int, b: int) -> bool:
        return any(a < e and s < b for s, e in taken)

    for m in _CASED_RE.finditer(text):
        tok = m.group(1)
        s, e = m.start(1), m.end(1)
        if overlaps(s, e):
            continue
        place = _resolve_cased(text, s, tok, out, short_codes)
        if place:
            out.append(Place(s, e, place[0], place[1], tok))
            taken.append((s, e))
    out.sort(key=lambda p: p.start)
    return out


def _resolve_cased(text: str, start: int, tok: str, prior: list[Place], short_codes: bool):
    before = text[:start]
    # "US-CA", "US-NYC", "US-REM": the prefix decides
    if re.search(r"\bUS\s?-\s?$", before) and (
        tok in G.US_STATES or tok in G.CITY_CODES_CASED or tok.startswith("REM")
    ):
        return ("US", "subdivision")
    if re.search(r"\bCanada\s?-\s?$", before, re.I) and tok in _CA_PROVINCES:
        return ("CA", "subdivision")
    m = re.search(r",\s*$", before)
    if m and short_codes:
        # what came right before the comma?
        prev = None
        for p in prior:
            if 0 <= m.start() - p.end <= 1:
                prev = p
        if prev is None or prev.kind in ("city", "subdivision"):
            if (prev is None or prev.code == "US") and tok in G.US_STATES:
                return ("US", "subdivision")
            if (prev is None or prev.code == "CA") and tok in _CA_PROVINCES:
                return ("CA", "subdivision")
    if tok in G.REGION_CODES_CASED:
        return (G.REGION_CODES_CASED[tok], "region")
    if tok in ("US", "USA", "UK", "UAE", "EU"):
        return (G.COUNTRY_CODES_CASED.get(tok, tok), "country")
    if not short_codes:
        return None
    if tok in G.COUNTRY_CODES_CASED:
        return (G.COUNTRY_CODES_CASED[tok], "country")
    if tok in G.CITY_CODES_CASED:
        return (G.CITY_CODES_CASED[tok], "city")
    if tok in _CA_PROVINCES and re.search(r"(Canada|Ontario|Toronto|Vancouver)", text):
        return ("CA", "subdivision")
    return None


# ------------------------------------------------------------ remote mode --

_REMOTE_RE = re.compile(r"\b(remote|remotely|distributed|wfh|work from home|anywhere|worldwide|us-rem)\b", re.I)
_HYBRID_RE = re.compile(r"\bhybrid\b", re.I)
_ONSITE_RE = re.compile(r"\b(on-?site|in[- ]office|in person)\b", re.I)


def remote_mode(location_texts: list[str], workplace_type: str | None) -> str:
    """Work mode from location strings and the ATS workplace field: remote, hybrid, onsite or unknown."""
    joined = " ; ".join(t for t in location_texts if t)
    wt = (workplace_type or "").lower().replace("-", "").replace("_", "")
    if wt == "remote" or _REMOTE_RE.search(joined):
        return "remote"
    if wt == "hybrid" or _HYBRID_RE.search(joined):
        return "hybrid"
    if wt == "onsite" or _ONSITE_RE.search(joined):
        return "onsite"
    places = find_places(joined)
    if places and all(p.kind == "region" for p in places):
        # "EMEA", "Latin America", "APAC": nobody has an office called EMEA.
        return "remote"
    if places:
        return "onsite"
    return "unknown"


# ---------------------------------------------------- location field parse --

_OPTION_SPLIT = re.compile(r"\s*(?:;|\||\n|\s/\s|/(?=[A-Z])|\bOR\b|\bor\b)\s*")


def _codes_with_exclusions(text: str, short_codes: bool) -> tuple[set[str], set[str]]:
    inc: set[str] = set()
    exc: set[str] = set()
    ex = _EXCLUDE_KW.search(text)
    cut = ex.start() if ex else len(text)
    for p in find_places(text, short_codes):
        (exc if p.start >= cut else inc).add(p.code)
    return inc, exc


def parse_location_field(location_texts: list[str]) -> tuple[set[str], set[str], list[str]]:
    """Returns (regions, excluded, evidence) from raw location strings."""
    regions: set[str] = set()
    excluded: set[str] = set()
    evidence: list[str] = []
    for raw in location_texts:
        if not raw or not raw.strip():
            continue
        raw = normalize_dashes(raw)
        for opt in _OPTION_SPLIT.split(raw):
            if not opt.strip():
                continue
            inc, exc = _codes_with_exclusions(opt, short_codes=True)
            # "Remote Global (US, EU)", "Anywhere in the US": a global word next to
            # specific places is a restriction, not an expansion.
            if "GLOBAL" in inc and len(inc) > 1:
                inc.discard("GLOBAL")
                evidence.append(f'location "{opt.strip()}" reads as global but names {", ".join(sorted(inc))}')
            regions |= inc
            # Sub-country exclusions ("Canada, excluding Quebec") keep the country.
            excluded |= {c for c in exc if c not in inc}
            if exc:
                evidence.append(f'location "{opt.strip()}" carves out an exclusion')
    return regions, excluded, evidence


# ------------------------------------------------- description restriction --

_SUBJ = re.compile(
    r"\b(you|your|candidates?|applicants?|individuals?|people|talent|hires?|hiring|employ\w*|"
    r"this (role|position|job|opportunity|team)|the (role|position)|eligib\w+|authori[sz]\w+|"
    r"right to work|residen\w+|reside|residing|open to)\b",
    re.I,
)
_GEO_VERB = re.compile(
    r"\b(located|based|reside|residing|residents?|resident|live|living|work from|working from|"
    r"remote|remotely|hire|hiring|employ|employing|eligible|authori[sz]ed|authori[sz]ation|"
    r"right to work|open to|anywhere|distributed|time ?zones?)\b",
    re.I,
)
# Company-self-description and pay-transparency sentences that name places
# without restricting who can apply.
_NOISE = re.compile(
    r"\b(our (customers|users|clients|offices?|investors|partners)|salary|base pay|pay range|"
    r"compensation|ote\b|equal opportunity|we have offices|headquartered|hq\b|backed by|"
    r"countries|markets)\b",
    re.I,
)
_NEG_HIRE = re.compile(
    r"\b(cannot|can't|can not|unable to|do not|don't|are not able to|aren't able to|not able to)\s+"
    r"(currently\s+)?(hire|employ|accept|consider|support)\b",
    re.I,
)
_ANYWHERE_RE = re.compile(
    r"\b(work from anywhere|anywhere in the world|hire (globally|anywhere|worldwide)|"
    r"fully remote,? (globally|worldwide)|remote,? (globally|worldwide)|location[- ]agnostic|"
    r"from any(where| country| location))\b",
    re.I,
)
_TZ_RE = re.compile(
    r"\b(?:(?:[A-Z]{2,4}|US|EU|European|Pacific|Eastern|Central|India|Asian|American)\s+)?time ?zones?\b"
    r"|\b(PST|PT|EST|ET|CST|CET|GMT|UTC|IST|SGT)\b(?:\s*[+-]\s*\d+)?",
)


def parse_description_geo(desc: str) -> tuple[set[str], set[str], list[str], list[str]]:
    """Returns (regions, excluded, evidence_sentences, timezone_notes)."""
    regions: set[str] = set()
    excluded: set[str] = set()
    evidence: list[str] = []
    tz_notes: list[str] = []
    if not desc:
        return regions, excluded, evidence, tz_notes
    for s in sentences(normalize_dashes(desc)):
        if len(s) > 600:
            s = s[:600]
        if not (_SUBJ.search(s) and _GEO_VERB.search(s)):
            continue
        if _NOISE.search(s):
            continue
        tz = re.search(r"\b(overlap|time ?zones?|hours)\b", s, re.I)
        places = find_places(s, short_codes=False)
        if _NEG_HIRE.search(s):
            codes = {p.code for p in places if p.code != "GLOBAL"}
            if codes:
                excluded |= codes
                evidence.append(s)
            continue
        if _ANYWHERE_RE.search(s) and not [p for p in places if p.code != "GLOBAL"]:
            regions.add("GLOBAL")
            evidence.append(s)
            continue
        if tz and not re.search(
            r"\b(located|based|reside|residing|resident|live|living|eligible|authori[sz]ed|hire|hiring)\b", s, re.I
        ):
            # "must overlap with US time zones" constrains hours, not residency.
            if places:
                tz_notes.append(s)
            continue
        inc: set[str] = set()
        exc: set[str] = set()
        cut = _EXCLUDE_KW.search(s)
        for p in places:
            (exc if cut and p.start >= cut.start() else inc).add(p.code)
        if "GLOBAL" in inc and len(inc) > 1:
            inc.discard("GLOBAL")
        if inc or exc:
            regions |= inc
            excluded |= {c for c in exc if c not in inc}
            evidence.append(s)
    return regions, excluded, evidence, tz_notes


# ------------------------------------------------------------------ combine --


@dataclass
class GeoResult:
    """Combined geography, work mode and sponsorship for one posting."""

    remote_mode: str
    regions: list[str]
    excluded: list[str]
    geo_scope: str
    geo_source: str
    sponsorship: str
    sponsorship_evidence: str | None = None
    evidence: list[str] = field(default_factory=list)
    timezone_notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        """Flatten into posting-schema fields."""
        return {
            "remote_mode": self.remote_mode,
            "regions": self.regions,
            "excluded_regions": self.excluded,
            "geo_scope": self.geo_scope,
            "geo_source": self.geo_source,
            "sponsorship": self.sponsorship,
            "sponsorship_evidence": self.sponsorship_evidence,
            "geo_evidence": self.evidence[:4],
            "timezone_notes": self.timezone_notes[:2],
        }


def parse_geo(
    location_texts: list[str],
    description: str = "",
    workplace_type: str | None = None,
    structured_countries: list[str] | None = None,
) -> GeoResult:
    """Parse eligible geography for one posting. See the module docstring for the order of trust."""
    location_texts = [t for t in (location_texts or []) if t and t.strip()]
    mode = remote_mode(location_texts, workplace_type)
    loc_regions, loc_exc, loc_ev = parse_location_field(location_texts)
    d_regions, d_exc, d_ev, tz = parse_description_geo(description)
    spons, spons_ev = parse_sponsorship(description)

    evidence = list(loc_ev)
    excluded = set(loc_exc)
    source = "location"
    if mode in ("onsite", "hybrid") and loc_regions:
        regions = set(loc_regions)
    else:
        loc_specific = loc_regions - {"GLOBAL"}
        d_specific = d_regions - {"GLOBAL"}
        if d_specific and not loc_specific:
            regions = d_specific
            source = "description"
            if "GLOBAL" in loc_regions:
                evidence.append("location says global but the description restricts it")
        elif d_specific and loc_specific:
            # The location field is the posting's own claim; description geography
            # here is usually company boilerplate ("our team spans the US, UK...").
            regions = set(loc_specific)
            if d_specific - loc_specific:
                evidence.append(
                    "description also names " + ", ".join(sorted(d_specific - loc_specific)) + " (not applied)"
                )
        elif loc_regions:
            regions = set(loc_regions)
        elif d_regions:
            regions = set(d_regions)
            source = "description"
        else:
            regions = set()
            source = "none"
        evidence += d_ev
        excluded |= d_exc
    if not regions and structured_countries:
        sc = {c for c in (_normalize_country(x) for x in structured_countries) if c}
        if sc:
            regions = sc
            source = "ats-country-field"
            evidence.append("only the ATS country field names a place: " + ", ".join(sorted(sc)))
    excluded -= regions
    if not regions:
        scope = "unspecified"
    elif regions == {"GLOBAL"}:
        scope = "global"
    else:
        regions.discard("GLOBAL")
        scope = "restricted"
    return GeoResult(mode, sorted(regions), sorted(excluded), scope, source, spons, spons_ev, evidence, tz)


def _normalize_country(x: str) -> str | None:
    if not x:
        return None
    x = x.strip()
    if x in ("USA", "US", "United States"):
        return "US"
    if x == "GB":
        return "UK"
    if len(x) == 2 and x.upper() in G.ALL_COUNTRY_CODES:
        return x.upper()
    for p in find_places(x):
        if p.kind in ("country", "city", "subdivision"):
            return p.code
    return None


def eligible(regions: list[str], excluded: list[str], country: str, scope: str) -> str:
    """Is someone living in `country` eligible? yes | no | unknown."""
    if country in (excluded or []):
        return "no"
    if scope == "unspecified" or not regions:
        return "unknown"
    return "yes" if any(G.region_contains(r, country) for r in regions) else "no"
