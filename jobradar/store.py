"""SQLite history + JSON snapshot.

SQLite keeps first_seen / last_seen / closed_at per posting across runs, which is
what powers the optional "new since" view. The JSON snapshot is the FULL current
set; search always runs over all of it.

Board-level failure semantics: if a board errors, its previously-known postings
stay in the snapshot marked stale. An error is never treated as "no jobs".
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
DB_PATH = DATA / "jobradar.sqlite"
SNAPSHOT_PATH = DATA / "snapshot.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  run_id TEXT PRIMARY KEY, started_at TEXT, finished_at TEXT,
  boards_ok INTEGER, boards_empty INTEGER, boards_error INTEGER,
  postings INTEGER, new_postings INTEGER, closed_postings INTEGER
);
CREATE TABLE IF NOT EXISTS boards (
  board TEXT PRIMARY KEY, ats TEXT, slug TEXT, company TEXT,
  last_status TEXT, last_count INTEGER, last_error TEXT, last_ok_at TEXT, last_run_id TEXT
);
CREATE TABLE IF NOT EXISTS postings (
  id TEXT PRIMARY KEY, board TEXT, first_seen TEXT, last_seen TEXT, closed_at TEXT, data TEXT
);
CREATE INDEX IF NOT EXISTS postings_board ON postings(board);
CREATE INDEX IF NOT EXISTS postings_first_seen ON postings(first_seen);
"""


def connect(path: Path = DB_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def record_run(con: sqlite3.Connection, run_id: str, started: str, finished: str,
               board_results: list[dict], postings_by_board: dict[str, list[dict]]) -> dict:
    """Idempotent upsert of one sweep. Returns counters."""
    new = closed = 0
    cur = con.cursor()
    for br in board_results:
        board = br["board"]
        cur.execute(
            "INSERT INTO boards(board, ats, slug, company, last_status, last_count, last_error, last_ok_at, last_run_id) "
            "VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(board) DO UPDATE SET company=excluded.company, "
            "last_status=excluded.last_status, last_count=excluded.last_count, last_error=excluded.last_error, "
            "last_ok_at=COALESCE(excluded.last_ok_at, boards.last_ok_at), last_run_id=excluded.last_run_id",
            (board, br["ats"], br["slug"], br["company"], br["status"], br.get("count"), br.get("error"),
             finished if br["status"] in ("ok", "empty") else None, run_id),
        )
        if br["status"] == "error":
            continue  # keep whatever we knew; never close postings on a failed fetch
        seen_ids = set()
        for p in postings_by_board.get(board, []):
            seen_ids.add(p["id"])
            row = cur.execute("SELECT first_seen FROM postings WHERE id=?", (p["id"],)).fetchone()
            if row is None:
                new += 1
                cur.execute("INSERT INTO postings(id, board, first_seen, last_seen, closed_at, data) VALUES(?,?,?,?,NULL,?)",
                            (p["id"], board, started, finished, json.dumps(p)))
            else:
                cur.execute("UPDATE postings SET last_seen=?, closed_at=NULL, data=? WHERE id=?",
                            (finished, json.dumps(p), p["id"]))
        open_ids = [r[0] for r in cur.execute("SELECT id FROM postings WHERE board=? AND closed_at IS NULL", (board,))]
        for pid in open_ids:
            if pid not in seen_ids:
                closed += 1
                cur.execute("UPDATE postings SET closed_at=? WHERE id=?", (finished, pid))
    ok = sum(1 for b in board_results if b["status"] == "ok")
    empty = sum(1 for b in board_results if b["status"] == "empty")
    err = sum(1 for b in board_results if b["status"] == "error")
    total = sum(len(v) for v in postings_by_board.values())
    cur.execute("INSERT OR REPLACE INTO runs VALUES(?,?,?,?,?,?,?,?,?)",
                (run_id, started, finished, ok, empty, err, total, new, closed))
    con.commit()
    return {"boards_ok": ok, "boards_empty": empty, "boards_error": err, "postings": total,
            "new_postings": new, "closed_postings": closed}


def current_postings(con: sqlite3.Connection, board_status: dict[str, str]) -> list[dict]:
    out = []
    for pid, board, first_seen, last_seen, data in con.execute(
            "SELECT id, board, first_seen, last_seen, data FROM postings WHERE closed_at IS NULL ORDER BY id"):
        if board not in board_status:
            continue  # board no longer in the seed list
        p = json.loads(data)
        p["first_seen"] = first_seen
        p["last_seen"] = last_seen
        p["stale"] = board_status.get(board) == "error"
        out.append(p)
    return out


def last_run_started(con: sqlite3.Connection) -> str | None:
    row = con.execute("SELECT started_at FROM runs ORDER BY started_at DESC LIMIT 1").fetchone()
    return row[0] if row else None


def write_snapshot(meta: dict, boards: list[dict], postings: list[dict], path: Path = SNAPSHOT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"meta": meta, "boards": boards, "postings": postings}, ensure_ascii=False))
    tmp.replace(path)


def load_snapshot(path: Path = SNAPSHOT_PATH) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"{path} not found. Run `jobradar sweep` first.")
    return json.loads(path.read_text())
