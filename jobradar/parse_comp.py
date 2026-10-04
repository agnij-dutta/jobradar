"""Compensation bands: structured (Ashby, Lever) first, description text as fallback."""

from __future__ import annotations

import re

from .textutil import normalize_dashes

# Approximate annual-salary conversion to USD. Good enough to filter, not to negotiate.
FX_TO_USD = {
    "USD": 1.0,
    "EUR": 1.08,
    "GBP": 1.27,
    "CAD": 0.73,
    "AUD": 0.66,
    "SGD": 0.75,
    "CHF": 1.12,
    "INR": 0.012,
    "JPY": 0.0067,
    "BRL": 0.18,
    "PLN": 0.25,
    "AED": 0.27,
    "HKD": 0.13,
    "NZD": 0.6,
    "SEK": 0.095,
    "DKK": 0.145,
    "NOK": 0.094,
    "MXN": 0.055,
    "ILS": 0.27,
    "CZK": 0.043,
}

_SYMBOL = {
    "$": "USD",
    "US$": "USD",
    "USD": "USD",
    "€": "EUR",
    "EUR": "EUR",
    "£": "GBP",
    "GBP": "GBP",
    "C$": "CAD",
    "CA$": "CAD",
    "CAD": "CAD",
    "A$": "AUD",
    "AU$": "AUD",
    "AUD": "AUD",
    "S$": "SGD",
    "SGD": "SGD",
    "CHF": "CHF",
    "₹": "INR",
    "INR": "INR",
    "Rs": "INR",
    "Rs.": "INR",
    "¥": "JPY",
    "JPY": "JPY",
    "R$": "BRL",
    "PLN": "PLN",
    "AED": "AED",
    "HK$": "HKD",
    "NZ$": "NZD",
    "SEK": "SEK",
    "zł": "PLN",
}

_CUR = r"(US\$|CA\$|AU\$|NZ\$|HK\$|C\$|A\$|S\$|R\$|\$|€|£|₹|¥|USD|EUR|GBP|CAD|AUD|SGD|CHF|INR|JPY|PLN|AED|SEK|Rs\.?)"
_AMT = r"(\d{1,3}(?:[,.\s]\d{2,3})+|\d+(?:\.\d+)?)\s*(k|K|m|M|L|lakhs?|lpa|LPA)?"
_RANGE = re.compile(
    rf"{_CUR}\s?{_AMT}\s*(?:{_CUR})?\s*(?:-|to|and)\s*{_CUR}?\s?{_AMT}\s*(?:{_CUR})?"
    r"(?:\s*(?:per|/|a)\s*(hour|hr|year|yr|annum|annually|month|mo))?",
)
_CUE = re.compile(r"\b(salary|base|compensation|pay|range|ote|annual|per year|wage|hourly|band|ctc|lpa)\b", re.I)


def _amount(num: str, suffix: str | None) -> float:
    n = num.replace(" ", "")
    if re.fullmatch(r"\d{1,3}(?:[,.]\d{3})+", n):
        n = re.sub(r"[,.]", "", n)
    elif re.fullmatch(r"\d{1,3}(?:,\d{2})+,\d{3}", n):  # Indian grouping 30,00,000
        n = n.replace(",", "")
    else:
        n = n.replace(",", "")
    v = float(n)
    s = (suffix or "").lower()
    if s == "k":
        v *= 1_000
    elif s == "m":
        v *= 1_000_000
    elif s in ("l", "lakh", "lakhs", "lpa"):
        v *= 100_000
    return v


def _band(cur: str, lo: float, hi: float, interval: str, source: str) -> dict | None:
    if lo <= 0 or hi < lo:
        return None
    mult = {"hour": 2080, "month": 12, "year": 1}.get(interval, 1)
    lo_a, hi_a = lo * mult, hi * mult
    fx = FX_TO_USD.get(cur)
    usd_lo = round(lo_a * fx) if fx else None
    usd_hi = round(hi_a * fx) if fx else None
    # sanity: annual salary between ~$3k and ~$2M
    if usd_lo is not None and usd_hi is not None and not (3_000 <= usd_lo <= 2_000_000 and usd_hi <= 3_000_000):
        return None
    return {
        "currency": cur,
        "min": lo,
        "max": hi,
        "interval": interval,
        "usd_min": usd_lo,
        "usd_max": usd_hi,
        "source": source,
    }


def from_ashby(comp: dict | None) -> dict | None:
    if not comp:
        return None
    for c in comp.get("summaryComponents") or []:
        if c.get("compensationType") == "Salary" and c.get("minValue"):
            iv = (c.get("interval") or "1 YEAR").upper()
            interval = "hour" if "HOUR" in iv else "month" if "MONTH" in iv else "year"
            return _band(
                c.get("currencyCode") or "USD",
                float(c["minValue"]),
                float(c.get("maxValue") or c["minValue"]),
                interval,
                "ats",
            )
    return None


def from_lever(sr: dict | None) -> dict | None:
    if not sr or not sr.get("min"):
        return None
    iv = (sr.get("interval") or "per-year-salary").lower()
    interval = "hour" if "hour" in iv else "month" if "month" in iv else "year"
    return _band(sr.get("currency") or "USD", float(sr["min"]), float(sr.get("max") or sr["min"]), interval, "ats")


def from_text(text: str) -> dict | None:
    if not text:
        return None
    t = normalize_dashes(text)
    for m in _RANGE.finditer(t):
        window = t[max(0, m.start() - 160) : m.end() + 40]
        if not _CUE.search(window):
            continue
        cur_tok = m.group(1) or m.group(4) or m.group(5) or m.group(8)
        cur = _SYMBOL.get(cur_tok.strip() if cur_tok else "$", "USD")
        lo_suf, hi_suf = m.group(3), m.group(7)
        if hi_suf and not lo_suf:
            lo_suf = hi_suf  # "$150-200K"
        try:
            lo = _amount(m.group(2), lo_suf)
            hi = _amount(m.group(6), hi_suf)
        except ValueError:
            continue
        unit = (m.group(9) or "").lower()
        if unit in ("hour", "hr") or (re.search(r"\b(per hour|/hr|hourly)\b", window, re.I) and hi < 1000):
            interval = "hour"
        elif unit in ("month", "mo"):
            interval = "month"
        else:
            interval = "year"
        b = _band(cur, lo, hi, interval, "description")
        if b:
            return b
    return None
