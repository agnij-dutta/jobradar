import json
import tempfile
import unittest
from pathlib import Path

from jobradar import store, webbuild
from jobradar.ats import normalize


class WebBuild(unittest.TestCase):
    def test_build_writes_loadable_data(self):
        job = {
            "id": "1",
            "title": "Backend Engineer\u2028(Platform)",
            "location": "Remote",
            "secondaryLocations": [],
            "workplaceType": "Remote",
            "jobUrl": "https://jobs.ashbyhq.com/acme/1",
            "descriptionPlain": "Open to candidates located in India. 2+ years of TypeScript experience.",
            "publishedAt": "2026-09-01T00:00:00Z",
        }
        p = normalize("ashby", "acme", "Acme", job)
        p["first_seen"] = "2026-09-01T00:00:00+00:00"
        with tempfile.TemporaryDirectory() as d:
            snap = Path(d) / "snapshot.json"
            store.write_snapshot(
                {"boards_total": 1, "finished_at": "2026-10-04T00:00:00+00:00"},
                [{"board": "ashby:acme", "status": "ok"}],
                [p],
                snap,
            )
            out = webbuild.build(str(snap), str(Path(d) / "dist"))
            js = (Path(out["out"]) / "data" / "jobs.js").read_text()
            self.assertTrue(js.startswith("window.JOBRADAR="))
            self.assertNotIn("\u2028", js)
            data = json.loads(js[len("window.JOBRADAR=") :].rstrip().rstrip(";"))
            row = data["postings"][0]
            self.assertEqual((row["m"], row["r"], row["y"]), ("r", ["IN"], 2))
            self.assertNotIn("description", row)
            self.assertEqual(data["meta"]["companies"][row["c"]][0], "Acme")
            self.assertEqual(data["meta"]["first_seen_values"][row["f"]], "2026-09-01T00:00:00")
            for f in ("index.html", "app.js", "style.css"):
                self.assertTrue((Path(out["out"]) / f).exists())


if __name__ == "__main__":
    unittest.main()
