"""ATS adapters: fetch a board and normalize every posting into one schema.

Each ATS is one `Adapter` in `ADAPTERS`. An adapter knows its two public
endpoints, how to find the job list in the response, and how to pull the raw
fields (title, url, description, location strings, ...) out of one job. All
parsing of those raw fields is shared, in `normalize`.

To add a source, write an adapter and register it. CONTRIBUTING.md walks through it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from . import parse_comp
from .http import FetchResult, get_json
from .parse_geo import parse_geo
from .parse_level import parse_level
from .stack import tag_counts
from .textutil import html_to_text


@dataclass
class RawFields:
    """What an adapter extracts from one job before any parsing."""

    job_id: str
    title: str
    url: str
    description: str
    locations: list[str]  # shown to the user as location_raw
    geo_locations: list[str] | None = None  # extra strings used only for geography (e.g. office names)
    team: str | None = None
    workplace_type: str | None = None  # the ATS's own remote/hybrid/onsite field, if any
    structured_countries: list[str] = field(default_factory=list)  # ATS country fields, last-resort geo
    comp: dict | None = None  # structured pay band, if the ATS publishes one
    posted_at: str | None = None
    updated_at: str | None = None
    employment_type: str | None = None
    company: str | None = None  # overrides the seed's company name when the ATS provides one


class Adapter:
    name: str = ""
    fetch_url: str = ""  # full board, with descriptions
    probe_url: str = ""  # cheapest call that proves the slug exists

    def jobs(self, data: Any) -> list[dict] | None:
        """Return the list of jobs in a response, or None if the shape is unexpected."""
        raise NotImplementedError

    def extract(self, job: dict) -> RawFields:
        raise NotImplementedError


def _iso(value: Any) -> str | None:
    """Normalize ISO strings and epoch milliseconds to UTC ISO-8601."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value / 1000, tz=timezone.utc).isoformat(timespec="seconds")
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc).isoformat(timespec="seconds")
    except ValueError:
        return str(value)


class Greenhouse(Adapter):
    name = "greenhouse"
    fetch_url = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    probe_url = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs"

    def jobs(self, data: Any) -> list[dict] | None:
        return data["jobs"] if isinstance(data, dict) and isinstance(data.get("jobs"), list) else None

    def extract(self, job: dict) -> RawFields:
        locations = [(job.get("location") or {}).get("name") or ""]
        offices = [o.get("name") for o in (job.get("offices") or []) if o.get("name")]
        desc = html_to_text(job.get("content"))  # Greenhouse double-escapes HTML
        return RawFields(
            job_id=str(job.get("id")),
            title=job.get("title") or "",
            url=job.get("absolute_url") or "",
            description=desc,
            locations=locations,
            geo_locations=locations + [o for o in offices if o not in locations],
            team=", ".join(d.get("name") for d in (job.get("departments") or []) if d.get("name")) or None,
            # The list endpoint has no structured pay; bands come from the text.
            comp=None,
            posted_at=_iso(job.get("first_published")),
            updated_at=_iso(job.get("updated_at")),
            company=job.get("company_name"),
        )


class Ashby(Adapter):
    name = "ashby"
    fetch_url = "https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true"
    probe_url = "https://api.ashbyhq.com/posting-api/job-board/{slug}"

    def jobs(self, data: Any) -> list[dict] | None:
        return data["jobs"] if isinstance(data, dict) and isinstance(data.get("jobs"), list) else None

    def extract(self, job: dict) -> RawFields:
        secondary = [s for s in (job.get("secondaryLocations") or []) if isinstance(s, dict)]
        locations = [job.get("location") or ""] + [s["location"] for s in secondary if s.get("location")]
        countries = []
        for address in [job.get("address")] + [s.get("address") for s in secondary]:
            country = ((address or {}).get("postalAddress") or {}).get("addressCountry")
            if country:
                countries.append(country)
        return RawFields(
            job_id=str(job.get("id")),
            title=job.get("title") or "",
            url=job.get("jobUrl") or "",
            description=job.get("descriptionPlain") or html_to_text(job.get("descriptionHtml")),
            locations=locations,
            team=job.get("team") or job.get("department"),
            workplace_type=job.get("workplaceType") or ("Remote" if job.get("isRemote") else None),
            structured_countries=countries,
            comp=parse_comp.from_ashby(job.get("compensation")),
            posted_at=_iso(job.get("publishedAt")),
            employment_type=job.get("employmentType"),
        )


class Lever(Adapter):
    name = "lever"
    fetch_url = "https://api.lever.co/v0/postings/{slug}?mode=json"
    probe_url = "https://api.lever.co/v0/postings/{slug}?mode=json&limit=1"

    def jobs(self, data: Any) -> list[dict] | None:
        return data if isinstance(data, list) else None

    def extract(self, job: dict) -> RawFields:
        # Lever splits the posting into an intro, titled lists (requirements live
        # here) and a closing section; stitch them back together in order.
        parts = [job.get("descriptionPlain") or ""]
        for block in job.get("lists") or []:
            parts += [block.get("text") or "", html_to_text(block.get("content"))]
        parts.append(job.get("additionalPlain") or "")
        categories = job.get("categories") or {}
        locations = [categories.get("location") or ""]
        locations += [loc for loc in (categories.get("allLocations") or []) if loc and loc not in locations]
        workplace = job.get("workplaceType")
        return RawFields(
            job_id=str(job.get("id")),
            title=job.get("text") or "",
            url=job.get("hostedUrl") or "",
            description="\n".join(p for p in parts if p),
            locations=locations,
            team=categories.get("team") or categories.get("department"),
            workplace_type=workplace if workplace not in (None, "unspecified") else None,
            structured_countries=[job["country"]] if job.get("country") else [],
            comp=parse_comp.from_lever(job.get("salaryRange")),
            posted_at=_iso(job.get("createdAt")),
            employment_type=categories.get("commitment"),
        )


ADAPTERS: dict[str, Adapter] = {a.name: a for a in (Greenhouse(), Ashby(), Lever())}

_ENG = re.compile(
    r"\b(engineer\w*|developer|swe|sde|software|programmer|backend|back-end|frontend|front-end|full[- ]?stack|"
    r"devops|sre|site reliability|protocol|smart contracts?|blockchain|solidity|rust|"
    r"machine learning|ml|researcher|research scientist|data scientist|cryptographer|architect|"
    r"founding|technical staff|tech lead)\b",
    re.I,
)
# Titles that contain "engineer" but are not software roles for this tool's purposes.
_NOT_ENG = re.compile(
    r"\b(sales|solutions|support|customer|success|account|recruit\w*|talent|people|marketing|counsel|legal|"
    r"compliance|designer|product manager|program manager|project manager|finance|accountant|"
    r"partnerships?|business development|bd|operations manager|community|content|writer|"
    r"implementation|onboarding|field|pre-?sales|go[- ]to[- ]market|gtm|strategy|operations|mechanical|electrical|civil|"
    r"facilities|data cent(er|re)|construction|hvac|commissioning|manufacturing|hardware technician)\b",
    re.I,
)


def is_engineering(title: str) -> bool:
    """True for software/engineering roles; excludes sales, solutions and facilities 'engineers'."""
    return bool(_ENG.search(title or "")) and not _NOT_ENG.search(title or "")


def fetch_board(ats: str, slug: str) -> FetchResult:
    return get_json(ADAPTERS[ats].fetch_url.format(slug=slug), timeout=90)


def probe_board(ats: str, slug: str) -> FetchResult:
    return get_json(ADAPTERS[ats].probe_url.format(slug=slug), timeout=30)


def raw_jobs(ats: str, data: Any) -> list[dict] | None:
    """Extract the job list, or None if the payload shape is unexpected."""
    return ADAPTERS[ats].jobs(data)


def normalize(ats: str, slug: str, company: str, job: dict) -> dict:
    """Turn one raw ATS job into the Job Radar schema (see README, "Schema")."""
    if ats not in ADAPTERS:
        raise ValueError(f"unknown ATS {ats!r}; known: {', '.join(ADAPTERS)}")
    raw = ADAPTERS[ats].extract(job)
    desc = raw.description
    geo = parse_geo(raw.geo_locations or raw.locations, desc, raw.workplace_type, raw.structured_countries)
    level = parse_level(raw.title, desc)
    record = {
        "id": f"{ats}:{slug}:{raw.job_id}",
        "ats": ats,
        "slug": slug,
        "company": raw.company or company,
        "title": raw.title.strip(),
        "url": raw.url,
        "team": raw.team,
        "location_raw": " | ".join(x for x in raw.locations if x),
        "employment_type": raw.employment_type,
        "is_engineering": is_engineering(raw.title),
        "comp": raw.comp or parse_comp.from_text(desc),
        "posted_at": raw.posted_at,
        "updated_at": raw.updated_at,
    }
    record.update(geo.as_dict())
    record.update(level.as_dict())
    record["tags"] = tag_counts(raw.title, desc)
    record["description"] = desc
    return record
