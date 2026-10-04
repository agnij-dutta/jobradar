import tempfile
import unittest
from pathlib import Path

from jobradar import parse_comp, store
from jobradar.ats import is_engineering, normalize
from jobradar.search import Query, run, summarize_exclusions
from jobradar.stack import score, tag_counts


class Comp(unittest.TestCase):
    def test_ashby_structured(self):
        c = parse_comp.from_ashby(
            {
                "summaryComponents": [
                    {
                        "compensationType": "Salary",
                        "interval": "1 YEAR",
                        "currencyCode": "USD",
                        "minValue": 170000,
                        "maxValue": 240000,
                    }
                ]
            }
        )
        self.assertEqual((c["usd_min"], c["usd_max"], c["source"]), (170000, 240000, "ats"))

    def test_lever_structured(self):
        c = parse_comp.from_lever({"min": 180000, "max": 220000, "currency": "USD", "interval": "per-year-salary"})
        self.assertEqual(c["usd_max"], 220000)

    def test_text_ranges(self):
        self.assertEqual(parse_comp.from_text("The base salary range is $150,000 - $200,000 USD.")["usd_min"], 150000)
        self.assertEqual(parse_comp.from_text("Salary: $170K – $240K")["usd_max"], 240000)
        self.assertEqual(parse_comp.from_text("Compensation: €80,000 - €100,000")["currency"], "EUR")
        c = parse_comp.from_text("Annual CTC: ₹30L - ₹45L")
        self.assertEqual((c["currency"], c["min"]), ("INR", 3_000_000))

    def test_text_without_pay_cue_is_ignored(self):
        self.assertIsNone(parse_comp.from_text("We raised $20M - $30M across two rounds."))


class Stack(unittest.TestCase):
    def test_go_language_vs_verb(self):
        self.assertNotIn("go", tag_counts("", "We go to market fast and go deep on problems."))
        self.assertIn("go", tag_counts("", "Our services are written in Go and Rust."))
        self.assertIn("go", tag_counts("", "Experience with golang"))

    def test_java_vs_javascript(self):
        t = tag_counts("", "Strong JavaScript skills")
        self.assertIn("javascript", t)
        self.assertNotIn("java", t)

    def test_score_explains(self):
        s, matched, missing = score(
            "Backend Engineer", "TypeScript, Node.js and Postgres. Some Solidity.", ["ts", "solidity", "rust"]
        )
        self.assertGreater(s, 0)
        self.assertEqual(missing, ["rust"])
        self.assertTrue(any(m.startswith("typescript") for m in matched))

    def test_engineering_classifier(self):
        self.assertTrue(is_engineering("Backend Engineer E2 - Ecosystem"))
        self.assertTrue(is_engineering("Member of Technical Staff"))
        self.assertFalse(is_engineering("Solutions Engineer"))
        self.assertFalse(is_engineering("Sales Engineer, EMEA"))
        self.assertFalse(is_engineering("Account Executive"))
        self.assertFalse(is_engineering("Data Center Mechanical Engineer"))
        self.assertFalse(is_engineering("Strategy & Operations, Infrastructure"))
        self.assertTrue(is_engineering("Software Engineer, Infrastructure"))


def _ashby_job(jid, title, loc, desc, workplace="Remote", comp=None):
    return {
        "id": jid,
        "title": title,
        "location": loc,
        "secondaryLocations": [],
        "isRemote": workplace == "Remote",
        "workplaceType": workplace,
        "jobUrl": f"https://jobs.ashbyhq.com/acme/{jid}",
        "descriptionPlain": desc,
        "publishedAt": "2026-09-01T00:00:00Z",
        "team": "Engineering",
        "compensation": comp,
    }


class Adapters(unittest.TestCase):
    def test_unknown_ats_is_an_error(self):
        with self.assertRaises(ValueError):
            normalize("workday", "acme", "Acme", {})

    def test_lever_sections_are_stitched(self):
        job = {
            "id": "x",
            "text": "Backend Engineer",
            "hostedUrl": "https://jobs.lever.co/acme/x",
            "descriptionPlain": "Intro.",
            "lists": [{"text": "Requirements", "content": "<li>4+ years of Go experience</li>"}],
            "categories": {"location": "Remote - Canada"},
            "workplaceType": "remote",
            "createdAt": 1767225600000,
        }
        p = normalize("lever", "acme", "Acme", job)
        self.assertEqual((p["min_years"], p["regions"], p["remote_mode"]), (4, ["CA"], "remote"))
        self.assertEqual(p["posted_at"], "2026-01-01T00:00:00+00:00")


class SearchEndToEnd(unittest.TestCase):
    def setUp(self):
        jobs = [
            _ashby_job(
                "1",
                "Software Engineer",
                "Remote",
                "Open to candidates located in the US or Canada. 6+ years of experience with TypeScript.",
            ),
            _ashby_job(
                "2",
                "Backend Engineer E2",
                "Bengaluru, India",
                "3+ years of experience with TypeScript, Node.js and Solidity.",
                workplace="OnSite",
            ),
            _ashby_job(
                "3", "Protocol Engineer", "Remote - Anywhere", "2+ years of Solidity experience. Work from anywhere."
            ),
            _ashby_job("4", "Account Executive", "Remote - Anywhere", "Sell things."),
            _ashby_job("5", "Frontend Engineer", "Remote", "React and TypeScript."),
        ]
        self.posts = [normalize("ashby", "acme", "Acme", j) for j in jobs]
        for p in self.posts:
            p["first_seen"] = "2026-09-01T00:00:00+00:00"

    def test_full_search_with_reasons(self):
        q = Query(stack=["typescript", "solidity"], region="IN", max_years=3)
        hits, misses = run(self.posts, q)
        titles = [h.posting["title"] for h in hits]
        self.assertEqual(titles, ["Backend Engineer E2", "Protocol Engineer"])
        reasons = {m.posting["title"]: " | ".join(m.reasons) for m in misses}
        self.assertIn("Remote, but only CA, US", reasons["Software Engineer"])
        self.assertIn("requires 6+ years", reasons["Software Engineer"])
        self.assertIn("never says where", reasons["Frontend Engineer"])
        self.assertIn("not an engineering title", reasons["Account Executive"])
        cats = dict(summarize_exclusions(misses))
        self.assertEqual(cats["geo: 'Remote' but restricted to other countries"], 1)

    def test_unverified_geo_is_opt_in(self):
        q = Query(stack=["react"], region="IN", include_unverified_geo=True)
        hits, _ = run(self.posts, q)
        self.assertEqual([h.posting["title"] for h in hits], ["Frontend Engineer"])
        self.assertTrue(any("unverified" in c for c in hits[0].caveats))

    def test_new_since_is_a_view(self):
        q = Query(new_since="2026-10-01T00:00:00+00:00")
        hits, misses = run(self.posts, q)
        self.assertEqual(hits, [])
        self.assertTrue(
            all(any("not new since" in r for r in m.reasons) for m in misses if m.posting["is_engineering"])
        )


class StoreSemantics(unittest.TestCase):
    def test_error_board_never_closes_postings(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(Path(d) / "t.sqlite")
            p = {"id": "ashby:acme:1", "title": "x"}
            board = {"board": "ashby:acme", "ats": "ashby", "slug": "acme", "company": "Acme"}
            store.record_run(con, "r1", "t1", "t1", [{**board, "status": "ok", "count": 1}], {"ashby:acme": [p]})
            # second run: the fetch failed. The posting must survive, marked stale.
            store.record_run(
                con, "r2", "t2", "t2", [{**board, "status": "error", "error": "timeout"}], {"ashby:acme": []}
            )
            cur = store.current_postings(con, {"ashby:acme": "error"})
            self.assertEqual(len(cur), 1)
            self.assertTrue(cur[0]["stale"])
            # third run: the board answered with zero jobs. Now it is closed.
            c = store.record_run(con, "r3", "t3", "t3", [{**board, "status": "empty", "count": 0}], {"ashby:acme": []})
            self.assertEqual(c["closed_postings"], 1)
            self.assertEqual(store.current_postings(con, {"ashby:acme": "empty"}), [])

    def test_rerun_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d:
            con = store.connect(Path(d) / "t.sqlite")
            p = {"id": "ashby:acme:1", "title": "x"}
            board = {
                "board": "ashby:acme",
                "ats": "ashby",
                "slug": "acme",
                "company": "Acme",
                "status": "ok",
                "count": 1,
            }
            a = store.record_run(con, "r1", "t1", "t1", [board], {"ashby:acme": [p]})
            b = store.record_run(con, "r2", "t2", "t2", [board], {"ashby:acme": [p]})
            self.assertEqual((a["new_postings"], b["new_postings"]), (1, 0))
            first = con.execute("SELECT first_seen FROM postings").fetchone()[0]
            self.assertEqual(first, "t1")
            self.assertEqual(con.execute("SELECT COUNT(*) FROM postings").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
