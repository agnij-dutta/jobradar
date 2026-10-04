"""Visa sponsorship parsing: yes, no or unknown, with the sentence it came from.

Explicit refusals win over offers. "Must already be authorized to work in X" is
read as an inferred no, and the evidence string says it was inferred.
"""

from __future__ import annotations

import re

from .textutil import normalize_dashes, sentences

_SPONSOR_WORD = re.compile(r"\b(sponsor\w*|visas?|immigration|work permits?)\b", re.I)
_SPONSOR_NEG = [
    re.compile(
        r"\b(no|not|unable to|cannot|can't|can not|won't|will not|do not|don't|does not|doesn't|"
        r"aren't able to|are not able to|isn't|is not|without|neither|nor)\b[^.]{0,70}?"
        r"\b(sponsor\w*|visas?|immigration|work permits?)\b",
        re.I,
    ),
    re.compile(
        r"\b(sponsor\w*|visas?)\b[^.]{0,50}?\b(not (available|offered|provided|possible|supported)|unavailable)\b", re.I
    ),
]
_SPONSOR_POS = re.compile(
    r"\b((visa |immigration |work permit )?sponsorship (is |are )?(available|offered|provided|possible)|"
    r"sponsor\w*\s*:\s*(yes|available)|open to sponsoring|supports? (visa|immigration) sponsorship|"
    r"(we|will|can|able to|happy to|do|does|are able to)\s+(also\s+)?(offer|provide|support)?\s*(visa\s+)?sponsor(ship|s|ing)?\b(?!\s+(is|are)\s+not)|"
    r"sponsor (your |work |employment )?visas?|relocation (and|&|\+) visa|visa (and|&|\+) relocation|"
    r"visa support|immigration support|support (with |for )?(your )?(visa|immigration)|"
    r"(offer|provide)s? (visa|immigration) (sponsorship|assistance|support))\b",
    re.I,
)
_SPONSOR_COLON_NO = re.compile(r"\bsponsor\w*\s*:\s*(no|none|not available|n/?a)\b", re.I)
# A negation that does not refuse: "we aren't able to sponsor visas for every role",
# "whether or not you need sponsorship", "you do not need to worry about visas",
# "we do not require existing work authorization".
_HEDGE = re.compile(
    r"\b(for (every|all|each) (role|position|candidate|applicant)s?|in (every|all) cases|whether or not|regardless of|"
    r"not sure|no need to|(do not|don't|doesn't|does not) need to worry|"
    r"(do not|don't|doesn't|does not) require (existing |prior |current )?(work )?(authori[sz]ation|visas?))\b",
    re.I,
)
# "sponsor" in a non-visa sense: export licenses, executive sponsors, event sponsorships,
# and EEO boilerplate about immigration status.
_NOT_VISA = re.compile(
    r"\b(export licen[cs]e|executive sponsors?|(event|conference|hackathon|corporate) sponsor\w*|"
    r"sponsor(s|ed|ing)? (events?|conferences?|hackathons?|meetups?))\b",
    re.I,
)
_EEO_STATUS = re.compile(r"\b(citizenship|immigration)( or (citizenship|immigration))? status\b", re.I)
_VISA_WORD = re.compile(r"\b(visas?|work permits?|h-?1b|immigration)\b", re.I)

_AUTH_REQ = re.compile(
    r"\b(must|need to|required to|should|will need to)\s+(already\s+)?(be|have)\s+(currently\s+)?(legally\s+)?"
    r"(authori[sz]ed|eligible|permitted|entitled|the right)\s+to\s+work\b",
    re.I,
)


def parse_sponsorship(desc: str) -> tuple[str, str | None]:
    """Returns (yes|no|unknown, evidence sentence)."""
    if not desc:
        return "unknown", None
    neg = pos = auth = None
    for s in sentences(normalize_dashes(desc)):
        text = _EEO_STATUS.sub(" ", s)
        if _NOT_VISA.search(text) and not _VISA_WORD.search(_NOT_VISA.sub(" ", text)):
            continue
        has_word = bool(_SPONSOR_WORD.search(text))
        if not has_word and not _AUTH_REQ.search(text):
            continue
        refused = has_word and (any(r.search(text) for r in _SPONSOR_NEG) or _SPONSOR_COLON_NO.search(text))
        if refused and not _HEDGE.search(text):
            neg = neg or s
        elif _SPONSOR_POS.search(text):
            pos = pos or s
        elif _AUTH_REQ.search(text) and not _HEDGE.search(text):
            auth = auth or s
    if neg:
        return "no", neg[:300]
    if pos:
        return "yes", pos[:300]
    if auth:
        return "no", "(inferred: requires existing work authorization) " + auth[:260]
    return "unknown", None
