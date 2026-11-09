"""Ingest MHRA safety communications published on GOV.UK.

Uses two public GOV.UK APIs (no key needed):
- Search API to list recent items: https://www.gov.uk/api/search.json
- Content API for each item's full text: https://www.gov.uk/api/content/<path>
Docs: https://docs.publishing.service.gov.uk/repos/search-api/using-the-search-api.html
"""

import logging
import time
from datetime import date, datetime

import requests

from regintel.ingest.html_text import html_to_text
from regintel.ingest.schema import NormalizedUpdate

log = logging.getLogger(__name__)

GOVUK_BASE = "https://www.gov.uk"
SEARCH_URL = f"{GOVUK_BASE}/api/search.json"
CONTENT_URL = f"{GOVUK_BASE}/api/content"

# GOV.UK document types that only MHRA publishes
DOCUMENT_TYPES = {
    "drug_safety_update": "Drug Safety Update",
    "medical_safety_alert": "Alerts, recalls and safety information",
}
SEARCH_FIELDS = [
    "title",
    "description",
    "link",
    "public_timestamp",
    "content_store_document_type",
]
PAGE_SIZE = 100
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _get_with_retry(http, url, params=None, timeout=30, attempts=3):
    for attempt in range(attempts):
        resp = http.get(url, params=params, timeout=timeout)
        if resp.status_code not in RETRY_STATUSES or attempt == attempts - 1:
            return resp
        wait = 2**attempt
        log.warning("GOV.UK returned %s, retrying in %ss", resp.status_code, wait)
        time.sleep(wait)
    return resp


def search_items(
    document_type: str,
    since: date,
    until: date | None = None,
    max_records: int = 500,
    session: requests.Session | None = None,
    timeout: int = 30,
) -> list[dict]:
    """List items of one document type published between `since` and `until`, newest first."""
    if document_type not in DOCUMENT_TYPES:
        raise ValueError(f"Unknown document_type {document_type!r}")

    http = session or requests.Session()
    until = until or date.today()
    results: list[dict] = []
    start = 0

    while len(results) < max_records:
        params = {
            "filter_content_store_document_type": document_type,
            "filter_public_timestamp": f"from:{since:%Y-%m-%d},to:{until:%Y-%m-%d}",
            "order": "-public_timestamp",
            "count": min(PAGE_SIZE, max_records - len(results)),
            "start": start,
            "fields": SEARCH_FIELDS,  # requests sends a list as repeated fields=... params
        }
        resp = _get_with_retry(http, SEARCH_URL, params, timeout)
        resp.raise_for_status()
        payload = resp.json()
        page = payload.get("results", [])
        results.extend(page)
        start += len(page)
        if not page or start >= payload.get("total", 0):
            break

    log.info("Found %d %s items since %s", len(results), document_type, since)
    return results


def fetch_content(
    link: str, session: requests.Session | None = None, timeout: int = 30
) -> dict:
    """Fetch the full content item for a GOV.UK path like '/drug-safety-update/...'."""
    http = session or requests.Session()
    resp = _get_with_retry(http, f"{CONTENT_URL}{link}", timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def _body_html(content: dict) -> str:
    """details.body is usually an HTML string, but some schemas use a list of typed parts."""
    body = (content.get("details") or {}).get("body") or ""
    if isinstance(body, list):
        html_parts = [
            p.get("content", "") for p in body if p.get("content_type") == "text/html"
        ]
        return "\n".join(html_parts)
    return body


def _parse_timestamp(value: str | None) -> date | None:
    try:
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


def normalize_item(search_result: dict, content: dict | None) -> NormalizedUpdate:
    """Combine a search result and its content item into a NormalizedUpdate."""
    link = search_result.get("link")
    if not link:
        raise ValueError("Search result has no link")

    document_type = search_result.get("content_store_document_type") or "unknown"
    description = (search_result.get("description") or "").strip()
    body = html_to_text(_body_html(content or {}))

    sections = []
    if description:
        sections.append(f"Summary: {description}")
    if body:
        sections.append(body)

    metadata = (content or {}).get("details", {}).get("metadata", {})

    return NormalizedUpdate(
        source="MHRA",
        source_type=document_type,
        source_id=link,
        title=(search_result.get("title") or link)[:500],
        url=f"{GOVUK_BASE}{link}",
        published_date=_parse_timestamp(search_result.get("public_timestamp")),
        body_text="\n\n".join(sections),
        raw={"search": search_result, "metadata": metadata, "body_text": body},
    )


def fetch_and_normalize(
    document_type: str,
    since: date,
    max_records: int = 500,
    session: requests.Session | None = None,
    delay: float = 0.1,
) -> list[NormalizedUpdate]:
    """Search, fetch each item's full text, and normalize. Items that fail are skipped."""
    http = session or requests.Session()
    records = []
    for result in search_items(
        document_type, since, max_records=max_records, session=http
    ):
        link = result.get("link")
        try:
            content = fetch_content(link, session=http) if link else None
            records.append(normalize_item(result, content))
        except (requests.RequestException, ValueError) as exc:
            log.warning("Skipping %s: %s", link, exc)
        if delay:
            time.sleep(delay)  # be polite to GOV.UK
    return records
