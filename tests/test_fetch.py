"""Fetch-layer tests: three-state results, politeness headers, sweep failure
semantics and the partial-probe merge. A local HTTP server stands in for the ATS."""

import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import ClassVar
from unittest import mock

from jobradar import http, seeds, sweep


class _Handler(BaseHTTPRequestHandler):
    seen_agents: ClassVar[list[str]] = []
    hits: ClassVar[dict[str, int]] = {}

    def do_GET(self):
        _Handler.seen_agents.append(self.headers.get("User-Agent", ""))
        _Handler.hits[self.path] = _Handler.hits.get(self.path, 0) + 1
        routes = {
            "/ok": (200, json.dumps({"jobs": []})),
            "/missing": (404, "nope"),
            "/broken": (500, "boom"),
            "/html": (200, "<html>not json</html>"),
        }
        code, body = routes.get(self.path, (404, ""))
        self.send_response(code)
        self.end_headers()
        self.wfile.write(body.encode())

    def log_message(self, *args):
        pass


class Http(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        # Retries back off with time.sleep; skip the waiting, keep the logic.
        patcher = mock.patch.object(http.time, "sleep", lambda s: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ok_sends_user_agent(self):
        r = http.get_json(self.base + "/ok", timeout=5)
        self.assertEqual((r.status, r.data), ("ok", {"jobs": []}))
        self.assertTrue(_Handler.seen_agents[-1].startswith("jobradar/"))

    def test_404_is_not_found(self):
        self.assertEqual(http.get_json(self.base + "/missing", timeout=5).status, "not_found")

    def test_5xx_retries_then_errors(self):
        r = http.get_json(self.base + "/broken", timeout=5)
        self.assertEqual((r.status, r.http_status), ("error", 500))
        self.assertEqual(_Handler.hits["/broken"], http.MAX_RETRIES + 1)

    def test_non_json_is_an_error_not_an_empty_board(self):
        self.assertEqual(http.get_json(self.base + "/html", timeout=5).status, "error")

    def test_connection_refused_is_an_error(self):
        self.assertEqual(http.get_json("http://127.0.0.1:9/x", timeout=2).status, "error")


BOARD = {"ats": "ashby", "slug": "acme", "company": "Acme", "category": "devtools"}


class SweepFailures(unittest.TestCase):
    def test_board_that_vanished_is_an_error(self):
        with mock.patch.object(sweep, "fetch_board", return_value=http.FetchResult("not_found", 404)):
            res, posts = sweep.fetch_one(BOARD)
        self.assertEqual((res["status"], posts), ("error", []))

    def test_every_job_failing_to_parse_is_an_error_not_ok(self):
        # "ok" with zero postings would close every posting this board had.
        payload = {"jobs": [{"id": "1"}, {"id": "2"}]}
        with (
            mock.patch.object(sweep, "fetch_board", return_value=http.FetchResult("ok", 200, payload)),
            mock.patch.object(sweep, "save_raw"),
            mock.patch.object(sweep, "normalize", side_effect=ValueError("schema changed")),
        ):
            res, posts = sweep.fetch_one(BOARD)
        self.assertEqual((res["status"], posts), ("error", []))
        self.assertIn("failed to parse", res["error"])


class ProbeMerge(unittest.TestCase):
    def test_partial_probe_keeps_everything_it_did_not_see(self):
        old = [
            {"ats": "ashby", "slug": "acme", "company": "Acme Inc (curated)", "category": "devtools"},
            {"ats": "lever", "slug": "flaky", "company": "Flaky"},
            {"ats": "greenhouse", "slug": "gone", "company": "Gone"},
            {"ats": "greenhouse", "slug": "untouched", "company": "Untouched"},
        ]
        old_dead = [{"slug": "olddead"}, {"slug": "acme"}]
        result = {
            "live": [{"ats": "ashby", "slug": "acme", "company": "acme", "category": None, "jobs_at_probe": 3}],
            "errors": [{"ats": "lever", "slug": "flaky", "status": "error"}],
            "dead": [{"slug": "gone"}],
        }
        boards, dead = seeds.merge_probe(old, old_dead, {"acme", "flaky", "gone"}, result)
        by_slug = {b["slug"]: b for b in boards}
        self.assertEqual(sorted(by_slug), ["acme", "flaky", "untouched"])
        self.assertEqual(by_slug["acme"]["company"], "Acme Inc (curated)")  # curated name survives
        self.assertEqual(by_slug["acme"]["jobs_at_probe"], 3)
        self.assertEqual([d["slug"] for d in dead], ["gone", "olddead"])  # acme answered, so it is not dead


if __name__ == "__main__":
    unittest.main()
