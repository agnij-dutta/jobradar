"""Geography parser tests. Location strings are real values seen on Greenhouse,
Ashby and Lever boards; description snippets are paraphrased from real postings."""
import unittest

from jobradar.parse_geo import eligible, parse_geo, parse_sponsorship


def geo(loc, desc="", wt=None, structured=None):
    return parse_geo([loc] if isinstance(loc, str) else loc, desc, wt, structured)


class LocationField(unittest.TestCase):
    def check(self, loc, mode, scope, regions):
        r = geo(loc)
        self.assertEqual((r.remote_mode, r.geo_scope, r.regions), (mode, scope, sorted(regions)), loc)

    def test_remote_with_country(self):
        self.check("Remote - USA", "remote", "restricted", ["US"])
        self.check("US remote", "remote", "restricted", ["US"])
        self.check("United Kingdom - Remote", "remote", "restricted", ["UK"])
        self.check("China (remote)", "remote", "restricted", ["CN"])
        self.check("Toronto, Canada Remote", "remote", "restricted", ["CA"])

    def test_bare_remote_is_unspecified_not_global(self):
        self.check("Remote", "remote", "unspecified", [])
        self.check("Remote ", "remote", "unspecified", [])

    def test_truly_global(self):
        self.check("Anywhere  (remote)", "remote", "global", ["GLOBAL"])
        self.check("Worldwide, but must be willing to attend regular EST meetings", "remote", "global", ["GLOBAL"])

    def test_global_word_with_named_places_is_a_restriction(self):
        self.check("Remote Global (US, EU)", "remote", "restricted", ["US", "EU"])

    def test_region_words(self):
        self.check("Remote Roles - APAC", "remote", "restricted", ["APAC"])
        self.check("LATAM - Remote", "remote", "restricted", ["LATAM"])
        self.check("EMEA", "remote", "restricted", ["EMEA"])
        self.check("South East Asia", "remote", "restricted", ["SEASIA"])
        self.check("North America (remote)", "remote", "restricted", ["NA"])

    def test_city_abbreviations(self):
        self.check("SF, SEA, NYC, CHI, ATL", "onsite", "restricted", ["US"])
        self.check("CHI, ATL, US-REM", "remote", "restricted", ["US"])
        self.check("US-NYC; US-SF; US-Chicago; US-Atlanta; US-Seattle; US-Remote", "remote", "restricted", ["US"])

    def test_state_codes_after_city_mean_us(self):
        self.check("New York, NY; San Francisco, CA; Seattle, WA; Chicago, IL", "onsite", "restricted", ["US"])
        self.check("Remote or Hybrid in Miami, FL", "remote", "restricted", ["US"])
        self.check("US-CA", "onsite", "restricted", ["US"])

    def test_ca_after_country_code_means_canada(self):
        self.check("Remote (US, CA)", "remote", "restricted", ["US", "CA"])

    def test_canadian_provinces(self):
        self.check("Vancouver, BC", "onsite", "restricted", ["CA"])
        self.check("Remote - Ontario or British Columbia", "remote", "restricted", ["CA"])

    def test_exclusion_keeps_country(self):
        r = geo("Canada Wide - Excluding Quebec (remote)")
        self.assertEqual(r.regions, ["CA"])
        self.assertEqual(r.remote_mode, "remote")

    def test_country_exclusion(self):
        r = geo("Europe (remote), excluding Germany")
        self.assertIn("EUROPE", r.regions)
        self.assertEqual(r.excluded, ["DE"])
        self.assertEqual(eligible(r.regions, r.excluded, "DE", r.geo_scope), "no")
        self.assertEqual(eligible(r.regions, r.excluded, "PL", r.geo_scope), "yes")

    def test_multi_country_lists(self):
        self.check("Malta / Spain / Bulgaria / Poland", "onsite", "restricted", ["MT", "ES", "BG", "PL"])
        self.check("London OR Paris OR Germany ", "onsite", "restricted", ["UK", "FR", "DE"])
        self.check("Poland - Remote OR Romania - Remote", "remote", "restricted", ["PL", "RO"])

    def test_india(self):
        self.check("Bengaluru, Karnataka", "onsite", "restricted", ["IN"])
        self.check("India, Bangalore ", "onsite", "restricted", ["IN"])
        self.check("Hybrid - Gurugram", "hybrid", "restricted", ["IN"])

    def test_latin_america_is_not_the_us(self):
        self.check("Latin America", "remote", "restricted", ["LATAM"])

    def test_sibling_cities_scope_a_bare_remote(self):
        self.check("Chicago, Atlanta, Remote", "remote", "restricted", ["US"])
        self.check("NYC Office (remote)", "remote", "restricted", ["US"])

    def test_noise(self):
        self.check("na", "unknown", "unspecified", [])

    def test_workplace_type_field(self):
        r = geo("New York, NY", wt="Hybrid")
        self.assertEqual((r.remote_mode, r.regions), ("hybrid", ["US"]))


class DescriptionRestrictions(unittest.TestCase):
    CARD = ("About the role\nWe are building the card stack for the internet. "
            "This role is fully remote and open to candidates located in the US, Canada (Ontario or British "
            "Columbia only), the Netherlands, Poland and Czechia. We are unable to offer visa sponsorship for "
            "this position.")

    def test_remote_restricted_by_description(self):
        r = geo("Remote", self.CARD, wt="Remote")
        self.assertEqual(r.geo_scope, "restricted")
        self.assertEqual(r.regions, ["CA", "CZ", "NL", "PL", "US"])
        self.assertEqual(r.geo_source, "description")
        self.assertEqual(r.sponsorship, "no")
        self.assertEqual(eligible(r.regions, r.excluded, "IN", r.geo_scope), "no")
        self.assertEqual(eligible(r.regions, r.excluded, "PL", r.geo_scope), "yes")

    def test_location_says_global_description_says_us(self):
        r = geo("Remote - Global", "You must be based in the United States to be considered for this role.")
        self.assertEqual(r.regions, ["US"])
        self.assertEqual(r.geo_scope, "restricted")

    def test_anywhere_in_the_us_is_not_anywhere(self):
        r = geo("Remote", "This position can be performed from anywhere in the US.")
        self.assertEqual(r.regions, ["US"])

    def test_company_hq_is_not_a_restriction(self):
        r = geo("Remote", "We are headquartered in San Francisco and have offices in London and Singapore. "
                          "Our customers are located in over 40 countries.")
        self.assertEqual(r.geo_scope, "unspecified")

    def test_pay_transparency_is_not_a_restriction(self):
        r = geo("Remote", "The base salary range for candidates located in California is $150,000 - $190,000.")
        self.assertEqual(r.geo_scope, "unspecified")

    def test_timezone_overlap_is_not_residency(self):
        r = geo("Remote", "You should be comfortable working with at least 4 hours of overlap with US Eastern time zones.")
        self.assertEqual(r.geo_scope, "unspecified")

    def test_work_from_anywhere(self):
        r = geo("Remote", "This is a remote position: you can work from anywhere in the world.")
        self.assertEqual(r.geo_scope, "global")

    def test_cannot_hire_in(self):
        r = geo("Remote - Europe", "Unfortunately we cannot hire candidates in Russia or Belarus, or in Germany at this time.")
        self.assertIn("DE", r.excluded)

    def test_ats_country_field_is_last_resort(self):
        r = geo("Remote", "", wt="Remote", structured=["USA"])
        self.assertEqual((r.regions, r.geo_source), (["US"], "ats-country-field"))
        r2 = geo("Remote - EMEA", "", wt="Remote", structured=["USA"])
        self.assertEqual(r2.regions, ["EMEA"])

    def test_onsite_ignores_description_geo(self):
        r = geo("Bengaluru, India", "Candidates in the US should apply to the NYC posting instead.", wt="OnSite")
        self.assertEqual(r.regions, ["IN"])


class Sponsorship(unittest.TestCase):
    def s(self, text):
        return parse_sponsorship(text)[0]

    def test_no(self):
        self.assertEqual(self.s("We are unable to sponsor visas at this time."), "no")
        self.assertEqual(self.s("Visa sponsorship is not available for this position."), "no")
        self.assertEqual(self.s("This role does not offer visa sponsorship."), "no")
        self.assertEqual(self.s("Candidates must be authorized to work in the US without sponsorship."), "no")

    def test_inferred_no(self):
        self.assertEqual(self.s("You must be legally authorized to work in Canada."), "no")

    def test_yes(self):
        self.assertEqual(self.s("We offer visa sponsorship and relocation support."), "yes")
        self.assertEqual(self.s("Relocation and visa support available for exceptional candidates."), "yes")
        self.assertEqual(self.s("We can sponsor visas for this role."), "yes")

    def test_unknown(self):
        self.assertEqual(self.s("Competitive salary, equity and a home-office budget."), "unknown")
        self.assertEqual(self.s(""), "unknown")


class Eligibility(unittest.TestCase):
    def test_region_membership(self):
        self.assertEqual(eligible(["APAC"], [], "IN", "restricted"), "yes")
        self.assertEqual(eligible(["EMEA"], [], "IN", "restricted"), "no")
        self.assertEqual(eligible(["EU"], [], "UK", "restricted"), "no")
        self.assertEqual(eligible(["EUROPE"], [], "UK", "restricted"), "yes")
        self.assertEqual(eligible(["GLOBAL"], [], "IN", "global"), "yes")
        self.assertEqual(eligible([], [], "IN", "unspecified"), "unknown")


if __name__ == "__main__":
    unittest.main()
