"""Full sweep: fetch every seeded board in parallel, normalize, store, snapshot."""
from __future__ import annotations

import concurrent.futures as cf
import gzip
import json
import time
import traceback
from datetime import datetime, timezone

from . import seeds, store
from .ats import fetch_board, normalize, raw_jobs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


RAW_DIR = store.DATA / "raw"


def raw_path(ats: str, slug: str):
    return RAW_DIR / f"{ats}__{slug}.json.gz"


def save_raw(ats: str, slug: str, data) -> None:
    """Bronze copy of the last good payload, so parsers can be re-run offline."""
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    tmp = raw_path(ats, slug).with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(data, f)
    tmp.replace(raw_path(ats, slug))


def normalize_jobs(b: dict, company: str, jobs: list[dict], res: dict) -> list[dict]:
    out, parse_errors, seen = [], 0, set()
    for j in jobs:
        try:
            p = normalize(b["ats"], b["slug"], company, j)
        except Exception:
            parse_errors += 1
            if parse_errors == 1:
                res["first_parse_error"] = traceback.format_exc(limit=2)[-400:]
            continue
        if p["id"] in seen:
            continue
        seen.add(p["id"])
        p["category"] = b.get("category")
        if b.get("company") and b["ats"] != "greenhouse":
            p["company"] = b["company"]
        out.append(p)
    res["parse_errors"] = parse_errors
    return out


def fetch_one(b: dict) -> tuple[dict, list[dict]]:
    board = f"{b['ats']}:{b['slug']}"
    t0 = time.monotonic()
    r = fetch_board(b["ats"], b["slug"])
    res = {"board": board, "ats": b["ats"], "slug": b["slug"], "company": b.get("company") or b["slug"],
           "category": b.get("category"), "elapsed_s": round(time.monotonic() - t0, 2)}
    if r.status == "not_found":
        # A verified board that now 404s is an ERROR, not an empty board.
        res.update(status="error", error=f"board missing ({r.http_status}); slug may have moved")
        return res, []
    if r.status != "ok":
        res.update(status="error", error=r.error)
        return res, []
    jobs = raw_jobs(b["ats"], r.data)
    if jobs is None:
        res.update(status="error", error="unexpected payload shape")
        return res, []
    save_raw(b["ats"], b["slug"], r.data)
    out = normalize_jobs(b, res["company"], jobs, res)
    if out:
        res["company"] = out[0]["company"] or res["company"]
    res.update(status="ok" if jobs else "empty", count=len(out))
    return res, out


def run(workers: int = 12, log=print, only: list[str] | None = None) -> dict:
    bl = seeds.boards()
    if only:
        bl = [b for b in bl if b["slug"] in only]
    if not bl:
        raise SystemExit("seeds/boards.json is empty. Run `jobradar probe` first.")
    started = _now()
    con = store.connect()
    prev_run = store.last_run_started(con)
    results: list[dict] = []
    postings_by_board: dict[str, list[dict]] = {}
    with cf.ThreadPoolExecutor(workers) as ex:
        futs = [ex.submit(fetch_one, b) for b in bl]
        for i, f in enumerate(cf.as_completed(futs), 1):
            res, posts = f.result()
            results.append(res)
            postings_by_board[res["board"]] = posts
            if res["status"] == "error":
                log(f"  ERROR {res['board']}: {res.get('error')}")
            if i % 50 == 0:
                log(f"  fetched {i}/{len(bl)} boards")
    finished = _now()
    counters = store.record_run(con, started, started, finished, results, postings_by_board)
    status = {r["board"]: r["status"] for r in results}
    current = store.current_postings(con, status)
    results.sort(key=lambda r: r["board"])
    meta = {
        "run_id": started, "started_at": started, "finished_at": finished,
        "previous_run_started_at": prev_run,
        "boards_total": len(results), **counters,
        "postings_in_snapshot": len(current),
        "stale_postings": sum(1 for p in current if p.get("stale")),
    }
    store.write_snapshot(meta, results, current)
    return meta


def reparse(log=print) -> dict:
    """Re-run every parser over the saved raw payloads. No network. Keeps
    first_seen history and board statuses from the last sweep."""
    snap = store.load_snapshot()
    con = store.connect()
    by_board = {f"{b['ats']}:{b['slug']}": b for b in seeds.boards()}
    status = {b["board"]: b["status"] for b in snap["boards"]}
    n = 0
    for board, st in status.items():
        b = by_board.get(board)
        if not b or st == "error" or not raw_path(b["ats"], b["slug"]).exists():
            continue
        with gzip.open(raw_path(b["ats"], b["slug"]), "rt", encoding="utf-8") as f:
            jobs = raw_jobs(b["ats"], json.load(f)) or []
        res: dict = {}
        for p in normalize_jobs(b, b.get("company") or b["slug"], jobs, res):
            n += con.execute("UPDATE postings SET data=? WHERE id=?", (json.dumps(p), p["id"])).rowcount
    con.commit()
    current = store.current_postings(con, status)
    meta = dict(snap["meta"], reparsed_at=_now(), postings_in_snapshot=len(current))
    store.write_snapshot(meta, snap["boards"], current)
    log(f"reparsed {n} postings from raw payloads")
    return meta
