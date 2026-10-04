"""Seniority parsing. A job title is not a level.

Two independent signals:

  years      minimum years of experience required, read from requirement text
             ("5+ years", "3-5 years", "at least four years", "2–10+ yrs").
             Preferred / nice-to-have mentions are tracked separately.
  level      a normalized ladder rung guessed from, in order of trust:
             required years > explicit level code (E2, L4, IC3, SWE II) > title words.

Ladder: intern(0) entry(1) junior(2) mid(3) senior(4) staff(5) principal(6) management(7)
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .textutil import lines, normalize_dashes, sentences

LEVELS = ["intern", "entry", "junior", "mid", "senior", "staff", "principal", "management"]
RANK = {name: i for i, name in enumerate(LEVELS)}

_WORDNUM = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
            "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20}
_NUM = r"(\d{1,2}(?:\.\d)?|" + "|".join(_WORDNUM) + r")"
_YRS = r"(?:years?|yrs?|yoe)\b"

_PATTERNS = [
    # 3-5 years, 3 to 5 years, 2-10+ yrs, (3 - 5) years
    re.compile(rf"\b{_NUM}\s*\+?\s*(?:-|to)\s*{_NUM}\s*\+?\s*(?:\)\s*)?{_YRS}", re.I),
    # at least 3 years, minimum of 4 years, over 5 years, more than 2 years
    re.compile(rf"\b(?:at least|a minimum of|minimum of|minimum|min\.?|over|more than|upwards of|no less than)\s+(?:\()?{_NUM}\s*\+?\s*(?:\)\s*)?{_YRS}", re.I),
    # 5+ years, 5 + yrs, 5 years, five (5) years, 3 or more years
    re.compile(rf"\b{_NUM}\s*(?:\(\s*\d{{1,2}}\s*\)\s*)?(?:\+|\s+or\s+more|\s+plus)?\s*{_YRS}", re.I),
    # Experience: 3+ / Years of experience: 5
    re.compile(rf"\b(?:years of experience|experience|yoe)\s*[:\-]\s*{_NUM}\s*\+?", re.I),
]

_EXPERIENCE_AFTER = re.compile(
    r"^[^.;\n]{0,90}?\b(experience|experienced|exp\b|background|track record|industry|professional|"
    r"hands-on|working|work\b|building|developing|development|engineering|programming|coding|writing|"
    r"shipping|in (a|an)\s|as (a|an)\s|of (software|backend|frontend|full|web|production|relevant|"
    r"related|applicable|smart|blockchain|crypto|distributed|systems|post)|yoe|in software|in tech|"
    r"in the industry|in fintech|in crypto|in web3|with\s|of\s|in\s)",
    re.I,
)
_EXPERIENCE_BEFORE = re.compile(r"(experience|yoe|seniority)[^.\n]{0,25}$", re.I)
_BAD_AFTER = re.compile(
    r"^\s*(?:-\s*)?(?:\+\s*)?(?:olds?|ago|degree|vesting|vest|of service|of tenure|sabbatical|warranty|runway|"
    r"in business|of operation|of age|anniversary|cliff|contract|term|of runway|history|of data|"
    r"of growth|in a row|program|programme|fellowship|plan|roadmap|horizon)\b",
    re.I,
)
_SELF_BEFORE = re.compile(r"\b(we have|we've|we bring|our team has|the team has|founders? (have|has|bring)|combined|collective)\b[^.]{0,30}$", re.I)
_BAD_BEFORE = re.compile(
    r"\b(within|in the (last|past|next)|"
    r"for the (last|past|next)|over the (last|past|next)|founded|since|after|every|each|per|"
    r"for (?:the )?first|up to|aged?|age of|turned|celebrat\w+|for)\s*(?:the\s+)?(?:over\s+)?$",
    re.I,
)
_BENEFITS = re.compile(r"\b(vest\w*|cliff|sabbatical|parental leave|pto|paid time off|equity|stock options?|runway)\b", re.I)
_PREFERRED_LINE = re.compile(
    r"\b(nice[- ]to[- ]have|bonus|a plus|is a plus|are a plus|pluses|preferred|ideally|desired|"
    r"would be great|we'd love|we would love|extra credit|brownie points|not required|isn't required|"
    r"is not required|don't need|do not need)\b",
    re.I,
)
_PREFERRED_HEADER = re.compile(r"\b(nice[- ]to[- ]haves?|bonus( points)?|preferred( qualifications| skills)?|pluses|extra credit|good to have)\b", re.I)
_REQUIRED_HEADER = re.compile(
    r"\b(requirements?|qualifications?|what you('ll)? (bring|need|have)|you (have|bring|are|might be)|"
    r"about you|who you are|must[- ]haves?|we('re| are) looking for|what we('re| are) looking for|"
    r"responsibilities|what you('ll)? do|the role|about the role|your background)\b",
    re.I,
)


def _num(s: str) -> float:
    s = s.lower()
    if s in _WORDNUM:
        return float(_WORDNUM[s])
    return float(s)


@dataclass
class YearsMention:
    value: float          # lower bound
    upper: float | None
    text: str
    preferred: bool
    line_no: int
    alternative: bool = False


def find_year_mentions(text: str) -> list[YearsMention]:
    text = normalize_dashes(text or "")
    out: list[YearsMention] = []
    section_preferred = False
    for ln_no, ln in enumerate(lines(text)):
        short = len(ln) < 70
        if short and _PREFERRED_HEADER.search(ln) and not re.search(r"\d", ln):
            section_preferred = True
            continue
        if short and _REQUIRED_HEADER.search(ln) and not re.search(r"\d", ln):
            section_preferred = False
            continue
        for sent in sentences(ln):
            if _BENEFITS.search(sent) and not re.search(r"\bexperience", sent, re.I):
                continue
            found: list[tuple[int, int, float, float | None]] = []
            for pi, pat in enumerate(_PATTERNS):
                for m in pat.finditer(sent):
                    s, e = m.start(), m.end()
                    if any(s < fe and fs < e for fs, fe, _, _ in found):
                        continue
                    after = sent[e:]
                    before = sent[:s]
                    if _BAD_AFTER.search(after):
                        continue
                    if re.search(r"\d\s*-?\s*$", before):
                        continue  # part of a larger number
                    if _SELF_BEFORE.search(before):
                        continue  # the company describing itself
                    if _BAD_BEFORE.search(before) and not _EXPERIENCE_AFTER.search(after):
                        continue
                    if pi < 3 and not (_EXPERIENCE_AFTER.search(after) or _EXPERIENCE_BEFORE.search(before)
                                       or re.search(r"yoe", m.group(0), re.I)):
                        continue
                    if pi == 0:
                        lo, hi = _num(m.group(1)), _num(m.group(2))
                        if hi < lo:
                            continue
                    else:
                        lo, hi = _num(m.group(1)), None
                    if lo > 25:
                        continue
                    found.append((s, e, lo, hi))
            found.sort()
            pref = section_preferred or bool(_PREFERRED_LINE.search(sent))
            for i, (s, e, lo, hi) in enumerate(found):
                alt = False
                if i > 0:
                    between = sent[found[i - 1][1]:s]
                    alt = bool(re.search(r"\bor\b", between, re.I))
                out.append(YearsMention(lo, hi, sent[max(0, s - 40):e + 60].strip(), pref, ln_no, alt))
    return out


def min_years(text: str) -> tuple[float | None, float | None, str | None]:
    """Returns (required_min_years, preferred_min_years, evidence)."""
    ms = find_year_mentions(text)
    if not ms:
        return None, None, None
    # Collapse "X years, or Y years with a Master's" into the lower option.
    groups: list[list[YearsMention]] = []
    for m in ms:
        if m.alternative and groups:
            groups[-1].append(m)
        else:
            groups.append([m])
    req: list[tuple[float, str]] = []
    pref: list[tuple[float, str]] = []
    for g in groups:
        best = min(g, key=lambda x: x.value)
        (pref if all(x.preferred for x in g) else req).append((best.value, best.text))
    r = max(req, key=lambda x: x[0]) if req else None
    p = max(pref, key=lambda x: x[0]) if pref else None
    ev = r[1] if r else (p[1] if p else None)
    return (r[0] if r else None), (p[0] if p else None), ev


# ------------------------------------------------------------- title level --

_TITLE_WORDS = [
    ("management", re.compile(r"\b(manager|director|head of|vp|vice president|chief|cto|ceo|cfo|coo|gm)\b", re.I)),
    ("principal", re.compile(r"\b(principal|distinguished|fellow)\b", re.I)),
    ("staff", re.compile(r"\b(staff|tech lead|technical lead|lead engineer|engineering lead|architect)\b", re.I)),
    ("senior", re.compile(r"\b(senior|sr\.?|snr|founding|lead)\b", re.I)),
    ("intern", re.compile(r"\b(intern|internship|co-?op)\b", re.I)),
    ("entry", re.compile(r"\b(new ?grad(uate)?|graduate|entry[- ]level|early[- ]career|university|campus|apprentice|residency)\b", re.I)),
    ("junior", re.compile(r"\b(junior|jr\.?|associate)\b", re.I)),
    ("mid", re.compile(r"\b(mid[- ]level|intermediate)\b", re.I)),
]

_CODE_RE = re.compile(
    r"(?:\(|\b(?:engineer|developer|swe|sde|scientist|programmer)\b[\s,\-–]{0,4}(?:[A-Za-z/&\s]{0,25}?[\s,\-–(]{1,3})?)"
    r"\s*\b(E|L|IC|P|T)\s?-?(\d{1,2})\b\)?",
    re.I,
)
_ROMAN_RE = re.compile(r"\b((?i:engineer|developer|swe|sde|programmer))\s*,?\s*(I{1,3}|IV|V|[1-5])\b(?!\s*(?:/|years))")
_ROMAN = {"I": 1, "II": 2, "III": 3, "IV": 4, "V": 5}

_CODE_MAP = {
    # Ladder families differ; these are the common public mappings.
    "L": {3: "entry", 4: "mid", 5: "senior", 6: "staff", 7: "principal", 8: "principal"},
    "E": {1: "junior", 2: "junior", 3: "entry", 4: "mid", 5: "senior", 6: "staff", 7: "principal", 8: "principal"},
    "IC": {1: "entry", 2: "junior", 3: "mid", 4: "senior", 5: "staff", 6: "principal", 7: "principal"},
    "P": {1: "entry", 2: "junior", 3: "mid", 4: "senior", 5: "staff", 6: "principal"},
    "T": {1: "entry", 2: "junior", 3: "mid", 4: "senior", 5: "staff", 6: "principal"},
    "N": {1: "entry", 2: "junior", 3: "senior", 4: "staff", 5: "principal"},
}


def level_code(title: str) -> tuple[str | None, str | None]:
    """Returns (code_text, level) for explicit ladder codes in a title."""
    t = normalize_dashes(title or "")
    m = _CODE_RE.search(t)
    if m:
        fam, n = m.group(1).upper(), int(m.group(2))
        # "L1"/"L2" in crypto titles are chains, not levels.
        if fam == "L" and n <= 2:
            m = None
        else:
            lvl = _CODE_MAP.get(fam, {}).get(n)
            if lvl:
                return f"{fam}{n}", lvl
    m = _ROMAN_RE.search(t)
    if m:
        tok = m.group(2)
        n = _ROMAN.get(tok) or int(tok)
        return f"{m.group(1)} {tok}", _CODE_MAP["N"].get(n)
    return None, None


def title_level(title: str) -> str | None:
    t = title or ""
    for name, rx in _TITLE_WORDS:
        if rx.search(t):
            return name
    return None


def level_from_years(y: float) -> str:
    if y < 1:
        return "entry"
    if y < 3:
        return "junior"
    if y < 5:
        return "mid"
    if y < 8:
        return "senior"
    if y < 11:
        return "staff"
    return "principal"


@dataclass
class LevelResult:
    min_years: float | None
    preferred_years: float | None
    years_evidence: str | None
    level: str | None
    level_source: str | None   # years | code | title | None
    title_level: str | None
    level_code: str | None
    plain_title: bool
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "min_years": self.min_years,
            "preferred_years": self.preferred_years,
            "years_evidence": self.years_evidence,
            "level": self.level,
            "level_source": self.level_source,
            "title_level": self.title_level,
            "level_code": self.level_code,
            "plain_title": self.plain_title,
            "level_notes": self.notes,
        }


def parse_level(title: str, description: str) -> LevelResult:
    req, pref, ev = min_years(description)
    code_txt, code_lvl = level_code(title)
    tl = title_level(title)
    plain = tl is None and code_txt is None
    notes: list[str] = []
    if tl in ("intern", "management"):
        lvl, src = tl, "title"
    elif req is not None:
        lvl, src = level_from_years(req), "years"
        if tl and RANK[lvl] != RANK[tl]:
            notes.append(f"title says {tl}, requirements say {lvl} ({req:g}+ years)")
        if plain and req >= 5:
            notes.append(f"plain title, but asks for {req:g}+ years")
    elif code_lvl:
        lvl, src = code_lvl, "code"
    elif tl:
        lvl, src = tl, "title"
    else:
        lvl, src = None, None
    return LevelResult(req, pref, ev, lvl, src, tl, code_txt, plain, notes)
