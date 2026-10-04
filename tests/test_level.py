"""Years-of-experience and level parser tests, from real requirement phrasings."""

import unittest

from jobradar.parse_level import level_code, min_years, parse_level


class Years(unittest.TestCase):
    def req(self, text):
        return min_years(text)[0]

    def test_plus(self):
        self.assertEqual(self.req("8+ years of professional software engineering experience"), 8)
        self.assertEqual(self.req("You have 5+ YoE"), 5)
        self.assertEqual(self.req("1+ year of experience"), 1)

    def test_ranges_take_lower_bound(self):
        self.assertEqual(self.req("3-5 years of experience building backend systems"), 3)
        self.assertEqual(self.req("2–10+ yrs building production software"), 2)
        self.assertEqual(self.req("We're looking for someone with 0-2 years of experience"), 0)

    def test_words(self):
        self.assertEqual(self.req("At least four years of experience with distributed systems"), 4)
        self.assertEqual(self.req("Five (5) or more years of related work experience"), 5)

    def test_minimum_of(self):
        self.assertEqual(self.req("Minimum of 2 years' experience in a software engineering role"), 2)

    def test_degree_alternatives_take_the_easier_path(self):
        self.assertEqual(
            self.req("Bachelor's degree and 5 years of experience, or a Master's and 3 years of experience"), 3
        )

    def test_highest_general_requirement_wins(self):
        txt = "Requirements\n- 6+ years of software engineering experience\n- 2+ years with Rust"
        self.assertEqual(self.req(txt), 6)

    def test_not_experience(self):
        for t in [
            "4-year degree in Computer Science",
            "Founded 7 years ago",
            "Our runway is 4 years",
            "After 5 years of service you get a sabbatical",
            "We have 10+ years of experience in payments.",
            "In the past 3 years we have grown 10x.",
            "Equity vests over 4 years with a 1 year cliff.",
        ]:
            self.assertIsNone(self.req(t), t)

    def test_401k_is_not_years(self):
        self.assertEqual(self.req("401k with 4% match. 2+ years of experience in Go."), 2)

    def test_preferred_section_is_separate(self):
        r, p, _ = min_years("Requirements\n- 3+ years of TypeScript\nBonus points\n- 7+ years in fintech")
        self.assertEqual((r, p), (3, 7))
        r, p, _ = min_years("Nice to have: 5+ years of Solidity experience")
        self.assertEqual((r, p), (None, 5))

    def test_stripe_style_plain_title(self):
        desc = (
            "Who you are\nWe're looking for someone who meets the minimum requirements to be considered for the role.\n"
            "Minimum requirements\n8+ years of professional experience writing high quality production level code\n"
            "Preferred qualifications\nExperience with Ruby and Java"
        )
        lv = parse_level("Software Engineer, Internal Systems", desc)
        self.assertEqual(lv.min_years, 8)
        self.assertTrue(lv.plain_title)
        self.assertEqual(lv.level, "staff")
        self.assertEqual(lv.level_source, "years")


class Levels(unittest.TestCase):
    def test_codes(self):
        self.assertEqual(level_code("Backend Engineer E2 - Ecosystem"), ("E2", "junior"))
        self.assertEqual(level_code("Senior Software Engineer (L5)"), ("L5", "senior"))
        self.assertEqual(level_code("Software Engineer, L4"), ("L4", "mid"))
        self.assertEqual(level_code("Backend Engineer IC3")[1], "mid")
        self.assertEqual(level_code("Software Engineer II")[1], "junior")
        self.assertEqual(level_code("SWE III")[1], "senior")

    def test_chain_layers_are_not_levels(self):
        self.assertEqual(level_code("L2 Protocol Engineer"), (None, None))
        self.assertEqual(level_code("Senior Engineer, L1 Client"), (None, None))

    def test_title_words(self):
        self.assertEqual(parse_level("Staff Engineer", "").level, "staff")
        self.assertEqual(parse_level("Software Engineer - Early Career", "").level, "entry")
        self.assertEqual(parse_level("Engineering Manager", "").level, "management")
        self.assertEqual(parse_level("Software Engineering Intern", "5+ years").level, "intern")

    def test_years_beat_title(self):
        lv = parse_level("Backend Engineer E2", "3+ years of experience with TypeScript and Node")
        self.assertEqual((lv.level, lv.level_source, lv.level_code), ("mid", "years", "E2"))
        self.assertFalse(lv.plain_title)

    def test_junior_title_senior_requirements(self):
        lv = parse_level("Junior Backend Engineer", "5+ years of backend experience")
        self.assertEqual(lv.level, "senior")
        self.assertTrue(any("title says junior" in n for n in lv.notes))

    def test_plain_title_flag(self):
        self.assertTrue(parse_level("Software Engineer, Payments", "").plain_title)
        self.assertFalse(parse_level("Senior Software Engineer", "").plain_title)


if __name__ == "__main__":
    unittest.main()
