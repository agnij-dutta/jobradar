"""Seed list management: probe candidate slugs on every ATS, keep the ones that
answer, record dead slugs separately, and flag likely name collisions."""

from __future__ import annotations

import concurrent.futures as cf
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from .ats import PROBE_ENDPOINTS, probe_board, raw_jobs

ROOT = Path(__file__).resolve().parent.parent
SEEDS = Path(os.environ.get("JOBRADAR_SEEDS_DIR") or ROOT / "seeds")


def load_json(name: str, default):
    p = SEEDS / name
    return json.loads(p.read_text()) if p.exists() else default


def boards() -> list[dict]:
    return load_json("boards.json", [])


def collisions() -> set[tuple[str, str]]:
    return {(c["ats"], c["slug"]) for c in load_json("collisions.json", [])}


def _pretty(slug: str) -> str:
    s = re.sub(r"-(careers|inc|hq|io|xyz|labs?)$", "", slug)
    return " ".join(w.capitalize() for w in re.split(r"[-_]", s))


def _identity_tokens(slug: str) -> list[str]:
    base = re.sub(r"-(careers|inc|hq|io|xyz|dev|bank|finance|tech|it|money|ai|labs?)$", "", slug)
    base = (
        re.sub(r"(labs|hq|inc|ai|io|finance|network|foundation|technologies|dotdev|careers|global|xyz)$", "", base)
        or base
    )
    toks = [base.replace("-", " "), base.replace("-", "")]
    return [t for t in toks if len(t) >= 3]


def _probe_one(ats: str, slug: str) -> dict:
    r = probe_board(ats, slug)
    out: dict = {"ats": ats, "slug": slug, "status": r.status, "http": r.http_status, "error": r.error}
    if r.status != "ok":
        return out
    jobs = raw_jobs(ats, r.data)
    if jobs is None:
        out.update(status="error", error="unexpected payload shape")
        return out
    out["jobs"] = len(jobs)
    # Identity check: does the board ever mention the company name we think it is?
    sample = jobs[:3]
    text = ""
    company_name = None
    for j in sample:
        if ats == "greenhouse":
            company_name = company_name or j.get("company_name")
            text += " " + (j.get("company_name") or "")
        elif ats == "ashby":
            text += " " + (j.get("descriptionPlain") or "")[:4000] + " " + (j.get("jobUrl") or "")
        else:
            text += " " + (j.get("descriptionPlain") or "")[:4000] + " " + (j.get("additionalPlain") or "")[:2000]
    out["company_name"] = company_name
    low = text.lower().replace("-", " ")
    toks = _identity_tokens(slug)
    if not jobs:
        out["identity"] = "empty-board"
    elif any(t in low or t in low.replace(" ", "") for t in toks):
        out["identity"] = "name-match"
    else:
        out["identity"] = "unconfirmed"
        out["sample_titles"] = [(j.get("title") or j.get("text") or "")[:80] for j in sample]
    return out


def probe(candidates: list[dict], workers: int = 12, log=print) -> dict:
    tasks = [(ats, c) for c in candidates for ats in PROBE_ENDPOINTS]
    results: list[tuple[dict, dict]] = []
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = {ex.submit(_probe_one, ats, c["slug"]): c for ats, c in tasks}
        for i, f in enumerate(cf.as_completed(futs), 1):
            results.append((futs[f], f.result()))
            if i % 200 == 0:
                log(f"  probed {i}/{len(tasks)}")
    coll = collisions()
    live: list[dict] = []
    review: list[dict] = []
    errors: list[dict] = []
    by_slug: dict[str, list[dict]] = {}
    for c, r in results:
        by_slug.setdefault(c["slug"], []).append(r)
        if r["status"] == "ok":
            if (r["ats"], r["slug"]) in coll:
                continue
            rec = {
                "ats": r["ats"],
                "slug": r["slug"],
                "company": r.get("company_name") or c.get("name") or _pretty(r["slug"]),
                "category": c.get("category"),
                "source": c.get("source"),
                "jobs_at_probe": r["jobs"],
                "identity": r["identity"],
            }
            live.append(rec)
            if r["identity"] == "unconfirmed":
                review.append({**rec, "sample_titles": r.get("sample_titles")})
        elif r["status"] == "error":
            errors.append(r)
    dead = []
    for c in candidates:
        rs = by_slug.get(c["slug"], [])
        if rs and all(r["status"] == "not_found" for r in rs):
            dead.append({"slug": c["slug"], "category": c.get("category"), "source": c.get("source")})
    live.sort(key=lambda r: (r["slug"], r["ats"]))
    return {
        "live": live,
        "dead": dead,
        "errors": errors,
        "review": review,
        "probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
