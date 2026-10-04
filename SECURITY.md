# Security policy

## Reporting a vulnerability

Please report security issues privately through GitHub's private vulnerability reporting: the **Security** tab of this repository, then **Report a vulnerability**. Please don't open a public issue for a security problem. Expect a first reply within a week.

## Scope

In scope:
- The `jobradar` Python package and CLI.
- The static web UI in `web/`, for example script injection through posting fields rendered in the page.
- How the fetcher handles untrusted API responses (malformed or hostile JSON).

## Non-goals

- Job Radar reads public, keyless job board APIs. It handles no credentials and no personal data about the user, and it sends nothing anywhere except requests to those APIs.
- Posting content is third-party data. Job Radar does not vouch for the accuracy or legitimacy of any posting, and parsed fields (eligibility, years, sponsorship, pay) are heuristics. See the Limitations section of the README.
- Availability or rate limits of the upstream ATS APIs.
