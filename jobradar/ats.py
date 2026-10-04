"""ATS adapters: fetch a board and normalize every posting into one schema."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from . import parse_comp
from .http import FetchResult, get_json
from .parse_geo import parse_geo
from .parse_level import parse_level
from .stack import tag_counts
from .textutil import html_to_text

ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json",
}
# Cheap endpoints used only to verify that a slug exists.
PROBE_ENDPOINTS = {
    "greenhouse": "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
    "ashby": "https://api.ashbyhq.com/posting-api/job-board/{slug}",
    "lever": "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1",
}
BOARD_URLS = {
    "greenhouse": "https://job-boards.greenhouse.io/{slug}",
    "ashby": "https://jobs.ashbyhq.com/{slug}",
    "lever": "https://jobs.lever.co/{slug}",
}

_ENG = re.compile(
    r"\b(engineer\w*|developer|swe|sde|software|programmer|backend|back-end|frontend|front-end|full[- ]?stack|"
    r"devops|sre|site reliability|protocol|smart contracts?|blockchain|solidity|rust|infrastructure|"
    r"machine learning|ml|researcher|research scientist|data scientist|cryptographer|architect|"
    r"founding|technical staff|tech lead)\b",
    re.I,
)
_NOT_ENG = re.compile(
    r"\b(sales|solutions|support|customer|success|account|recruit\w*|talent|marketing|counsel|legal|"
    r"compliance|designer|product manager|program manager|project manager|finance|accountant|"
    r"partnerships?|business development|bd|operations manager|community|content|writer|"
    r"implementation|onboarding|field|pre-?sales|go[- ]to[- ]market|gtm)\b",
    re.I,
)


def is_engineering(title: str) -> bool:
    return bool(_ENG.search(title or "")) and not _NOT_ENG.search(title or "")


def fetch_board(ats: str, slug: str) -> FetchResult:
    return get_json(ENDPOINTS[ats].format(slug=slug), timeout=90)


def probe_board(ats: str, slug: str) -> FetchResult:
    return get_json(PROBE_ENDPOINTS[ats].format(slug=slug), timeout=30)


def raw_jobs(ats: str, data) -> list[dict] | None:
    """Extract the job list, or None if the payload shape is unexpected."""
    if ats in ("greenhouse", "ashby"):
        if isinstance(data, dict) and isinstance(data.get("jobs"), list):
            return data["jobs"]
        return None
    if ats == "lever":
        return data if isinstance(data, list) else None
    return None


def _iso(v) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    try:
        return datetime.fromisoformat(str(v).replace("Z", "+00:00")).astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return str(v)


def normalize(ats: str, slug: str, company: str, j: dict) -> dict:
    if ats == "greenhouse":
        title = j.get("title") or ""
        url = j.get("absolute_url") or ""
        jid = str(j.get("id"))
        desc = html_to_text(j.get("content"))
        locs = [(j.get("location") or {}).get("name") or ""]
        offices = [o.get("name") for o in (j.get("offices") or []) if o.get("name")]
        locs_for_geo = locs + [o for o in offices if o not in locs]
        team = ", ".join(d.get("name") for d in (j.get("departments") or []) if d.get("name")) or None
        workplace = None
        structured = []
        comp = parse_comp.from_text(desc)
        posted = _iso(j.get("first_published"))
        updated = _iso(j.get("updated_at"))
        company = j.get("company_name") or company
        employment = None
    elif ats == "ashby":
        title = j.get("title") or ""
        url = j.get("jobUrl") or ""
        jid = str(j.get("id"))
        desc = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))
        locs = [j.get("location") or ""]
        for sl in j.get("secondaryLocations") or []:
            if isinstance(sl, dict) and sl.get("location"):
                locs.append(sl["location"])
        locs_for_geo = list(locs)
        team = j.get("team") or j.get("department")
        workplace = j.get("workplaceType") or ("Remote" if j.get("isRemote") else None)
        structured = []
        for a in [j.get("address")] + [sl.get("address") for sl in (j.get("secondaryLocations") or []) if isinstance(sl, dict)]:
            c = ((a or {}).get("postalAddress") or {}).get("addressCountry")
            if c:
                structured.append(c)
        comp = parse_comp.from_ashby(j.get("compensation")) or parse_comp.from_text(desc)
        posted = _iso(j.get("publishedAt"))
        updated = None
        employment = j.get("employmentType")
    elif ats == "lever":
        title = j.get("text") or ""
        url = j.get("hostedUrl") or ""
        jid = str(j.get("id"))
        parts = [j.get("descriptionPlain") or ""]
        for li in j.get("lists") or []:
            parts.append(li.get("text") or "")
            parts.append(html_to_text(li.get("content")))
        parts.append(j.get("additionalPlain") or "")
        desc = "\n".join(p for p in parts if p)
        cats = j.get("categories") or {}
        locs = [cats.get("location") or ""]
        for al in cats.get("allLocations") or []:
            if al and al not in locs:
                locs.append(al)
        locs_for_geo = list(locs)
        team = cats.get("team") or cats.get("department")
        workplace = j.get("workplaceType") if j.get("workplaceType") not in (None, "unspecified") else None
        structured = [j["country"]] if j.get("country") else []
        comp = parse_comp.from_lever(j.get("salaryRange")) or parse_comp.from_text(desc)
        posted = _iso(j.get("createdAt"))
        updated = None
        employment = cats.get("commitment")
    else:
        raise ValueError(ats)

    geo = parse_geo(locs_for_geo, desc, workplace, structured)
    lvl = parse_level(title, desc)
    rec = {
        "id": f"{ats}:{slug}:{jid}",
        "ats": ats,
        "slug": slug,
        "company": company,
        "title": title.strip(),
        "url": url,
        "team": team,
        "location_raw": " | ".join(x for x in locs if x),
        "employment_type": employment,
        "is_engineering": is_engineering(title),
        "comp": comp,
        "posted_at": posted,
        "updated_at": updated,
    }
    rec.update(geo.as_dict())
    rec.update(lvl.as_dict())
    rec["tags"] = tag_counts(title, desc)
    rec["description"] = desc
    return rec
