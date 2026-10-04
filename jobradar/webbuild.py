"""Build the static web UI: copy web/ into dist/ and write a slim data file.

The slim file drops descriptions and keeps precomputed fields plus stack-term
counts, so the browser can filter thousands of postings instantly. It is a
<script> (window.JOBRADAR = ...) rather than JSON so dist/index.html also works
when opened straight from disk.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from . import geo_data, store
from .parse_level import LEVELS
from .stack import ALIASES, VOCAB

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"
DIST = ROOT / "dist"

_MODE = {"remote": "r", "hybrid": "h", "onsite": "o", "unknown": "u"}
_SCOPE = {"global": "g", "restricted": "r", "unspecified": "u"}
_VISA = {"yes": "y", "no": "n", "unknown": "u"}


def _short(s: str | None, n: int) -> str | None:
    if not s:
        return None
    s = " ".join(s.split())
    return s if len(s) <= n else s[: n - 3].rstrip() + "..."


def slim(p: dict) -> dict:
    c = p.get("comp") or {}
    out = {
        "c": p.get("company"), "t": p.get("title"), "u": p.get("url"), "tm": p.get("team"),
        "l": _short(p.get("location_raw"), 120), "m": _MODE.get(p.get("remote_mode"), "u"),
        "r": p.get("regions") or [], "s": _SCOPE.get(p.get("geo_scope"), "u"),
        "v": _VISA.get(p.get("sponsorship"), "u"), "e": 1 if p.get("is_engineering") else 0,
        "f": (p.get("first_seen") or "")[:19], "d": (p.get("posted_at") or p.get("updated_at") or "")[:10],
        "k": p.get("tags") or {}, "cat": p.get("category"),
    }
    if p.get("excluded_regions"):
        out["x"] = p["excluded_regions"]
    if p.get("min_years") is not None:
        out["y"] = p["min_years"]
    if p.get("preferred_years") is not None:
        out["py"] = p["preferred_years"]
    if p.get("level"):
        out["lv"] = LEVELS.index(p["level"])
        out["ls"] = p.get("level_source")
    if p.get("title_level"):
        out["tl"] = p["title_level"]
    if p.get("plain_title"):
        out["pt"] = 1
    if c.get("usd_max"):
        out["cp"] = [c.get("usd_min"), c.get("usd_max"), c.get("currency"), c.get("source")]
    ge = (p.get("geo_evidence") or [None])[0]
    if ge:
        out["ge"] = _short(ge, 200)
    if p.get("years_evidence"):
        out["ye"] = _short(p["years_evidence"], 140)
    if p.get("sponsorship_evidence"):
        out["ve"] = _short(p["sponsorship_evidence"], 160)
    if p.get("stale"):
        out["st"] = 1
    return out


def build(snapshot_path: str | None = None, out_dir: str | None = None) -> dict:
    snap = store.load_snapshot(Path(snapshot_path) if snapshot_path else store.SNAPSHOT_PATH)
    out = Path(out_dir) if out_dir else DIST
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(WEB, out)
    data_dir = out / "data"
    data_dir.mkdir(exist_ok=True)
    meta = dict(snap["meta"])
    meta["levels"] = LEVELS
    meta["region_members"] = geo_data.REGION_MEMBERS
    meta["countries"] = sorted(set(geo_data.COUNTRIES) | set(geo_data.CITIES))
    meta["vocab"] = sorted(VOCAB)
    meta["aliases"] = ALIASES
    meta["board_status"] = {
        "ok": sum(1 for b in snap["boards"] if b["status"] == "ok"),
        "empty": sum(1 for b in snap["boards"] if b["status"] == "empty"),
        "error": sum(1 for b in snap["boards"] if b["status"] == "error"),
        "errors": [b["board"] for b in snap["boards"] if b["status"] == "error"],
    }
    postings = [slim(p) for p in snap["postings"]]
    payload = json.dumps({"meta": meta, "postings": postings}, ensure_ascii=False, separators=(",", ":"))
    (data_dir / "jobs.js").write_text("window.JOBRADAR=" + payload + ";\n")
    return {"out": str(out), "postings": len(postings), "bytes": len(payload)}
