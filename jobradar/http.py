"""Polite HTTP: per-host concurrency caps, spacing between requests, retries with
backoff on 429/5xx, Retry-After honoured. Stdlib only.

Every call returns a FetchResult with an explicit status so that a network error
can never be mistaken for "this company has no jobs".
"""
from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from urllib.parse import urlparse

USER_AGENT = "jobradar/0.1 (open-source job search; polite crawler)"

PER_HOST_CONCURRENCY = 3
MIN_INTERVAL_S = 0.25  # per host, between request starts
MAX_RETRIES = 3

_host_sems: dict[str, threading.Semaphore] = {}
_host_last: dict[str, float] = {}
_lock = threading.Lock()


@dataclass
class FetchResult:
    status: str            # ok | not_found | error
    http_status: int | None
    data: object = None
    error: str | None = None
    elapsed_s: float = 0.0


def _gate(host: str) -> threading.Semaphore:
    with _lock:
        if host not in _host_sems:
            _host_sems[host] = threading.Semaphore(PER_HOST_CONCURRENCY)
            _host_last[host] = 0.0
        return _host_sems[host]


def _space(host: str) -> None:
    while True:
        with _lock:
            now = time.monotonic()
            wait = _host_last[host] + MIN_INTERVAL_S - now
            if wait <= 0:
                _host_last[host] = now
                return
        time.sleep(wait)


def get_json(url: str, timeout: float = 45.0) -> FetchResult:
    host = urlparse(url).netloc
    sem = _gate(host)
    t0 = time.monotonic()
    last_err = None
    last_code = None
    for attempt in range(MAX_RETRIES + 1):
        with sem:
            _space(host)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    body = r.read()
                    code = r.status
                try:
                    data = json.loads(body.decode("utf-8"))
                except (ValueError, UnicodeDecodeError) as e:
                    return FetchResult("error", code, None, f"invalid JSON: {e}", time.monotonic() - t0)
                return FetchResult("ok", code, data, None, time.monotonic() - t0)
            except urllib.error.HTTPError as e:
                last_code = e.code
                if e.code in (404, 410):
                    return FetchResult("not_found", e.code, None, f"HTTP {e.code}", time.monotonic() - t0)
                last_err = f"HTTP {e.code}"
                retry_after = e.headers.get("Retry-After") if e.headers else None
                if e.code == 429 or e.code >= 500:
                    delay = float(retry_after) if (retry_after and retry_after.isdigit()) else 1.5 * (2 ** attempt)
                    time.sleep(min(delay, 30))
                    continue
                return FetchResult("error", e.code, None, last_err, time.monotonic() - t0)
            except Exception as e:  # timeouts, DNS, resets
                last_err = f"{type(e).__name__}: {e}"
                time.sleep(1.0 * (2 ** attempt))
                continue
    return FetchResult("error", last_code, None, last_err, time.monotonic() - t0)
