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
    r"\b(visa sponsorship (is )?(available|offered|provided|possible)|"
    r"(we|will|can|able to|happy to|do|does|are able to)\s+(also\s+)?(offer|provide|support)?\s*(visa\s+)?sponsor(ship|s|ing)?\b(?!\s+(is|are)\s+not)|"
    r"sponsor (your |work |employment )?visas?|relocation (and|&|\+) visa|visa (and|&|\+) relocation|"
    r"visa support|immigration support|support (with |for )?(your )?(visa|immigration)|"
    r"(offer|provide)s? (visa|immigration) (sponsorship|assistance|support))\b",
    re.I,
)
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
        if not _SPONSOR_WORD.search(s) and not _AUTH_REQ.search(s):
            continue
        if _SPONSOR_WORD.search(s) and any(r.search(s) for r in _SPONSOR_NEG):
            neg = neg or s
        elif _SPONSOR_POS.search(s):
            pos = pos or s
        elif _AUTH_REQ.search(s):
            auth = auth or s
    if neg:
        return "no", neg[:300]
    if pos:
        return "yes", pos[:300]
    if auth:
        return "no", "(inferred: requires existing work authorization) " + auth[:260]
    return "unknown", None
