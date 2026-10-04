"""Text helpers: HTML to plain text, sentence/line splitting, dash normalization."""

import html
import re

_TAG = re.compile(r"<[^>]+>")
_BLOCK = re.compile(r"</?(p|div|br|li|ul|ol|h[1-6]|tr|section|article)\b[^>]*>", re.I)
_WS = re.compile(r"[ \t ]+")


def html_to_text(s: str | None) -> str:
    """Greenhouse double-escapes HTML; unescape until stable, then strip tags.

    Block-level tags become newlines so section headers ("Nice to have") stay
    on their own line, which the years parser relies on.
    """
    if not s:
        return ""
    for _ in range(3):
        u = html.unescape(s)
        if u == s:
            break
        s = u
    s = _BLOCK.sub("\n", s)
    s = _TAG.sub(" ", s)
    s = html.unescape(s)
    s = _WS.sub(" ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def normalize_dashes(s: str) -> str:
    """Replace en dashes, em dashes and similar with '-' so ranges parse."""
    # Escapes rather than literal characters so the source stays ASCII-readable.
    for dash in ("\u2013", "\u2014", "\u2012", "\u2212", "\u2011"):
        s = s.replace(dash, "-")
    return s


_SENT = re.compile(r"(?<=[.!?;])\s+(?=[A-Z(\"'])|\n+")


def sentences(text: str) -> list[str]:
    """Split text into sentences and lines."""
    return [p.strip() for p in _SENT.split(text) if p and p.strip()]


def lines(text: str) -> list[str]:
    """Non-empty, stripped lines."""
    return [ln.strip() for ln in text.split("\n") if ln.strip()]
