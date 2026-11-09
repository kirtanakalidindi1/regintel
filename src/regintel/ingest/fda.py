"""Ingest FDA recall (enforcement) reports from the openFDA API.

openFDA docs: https://open.fda.gov/apis/
"""

import logging
import time
from datetime import date, datetime
from urllib.parse import quote

import requests

from regintel.ingest.schema import NormalizedUpdate

log = logging.getLogger(__name__)

OPENFDA_BASE = "https://api.fda.gov"
ENFORCEMENT_ENDPOINTS = {
    "drug_enforcement": "/drug/enforcement.json",
    "device_enforcement": "/device/enforcement.json",
}
PAGE_SIZE = 100
MAX_SKIP = 25_000  # openFDA refuses skip values above this
RETRY_STATUSES = {429, 500, 502, 503, 504}


def _get_with_retry(http, url, params, timeout, attempts=3):
    for attempt in range(attempts):
        resp = http.get(url, params=params, timeout=timeout)
        if resp.status_code not in RETRY_STATUSES or attempt == attempts - 1:
            return resp
        wait = 2**attempt
        log.warning("openFDA returned %s, retrying in %ss", resp.status_code, wait)
        time.sleep(wait)
    return resp


def fetch_enforcement(
    source_type: str,
    since: date,
    until: date | None = None,
    max_records: int = 500,
    session: requests.Session | None = None,
    api_key: str | None = None,
    timeout: int = 30,
) -> list[dict]:
    """Fetch raw enforcement reports with a report_date between `since` and `until`."""
    if source_type not in ENFORCEMENT_ENDPOINTS:
        raise ValueError(f"Unknown source_type {source_type!r}")

    http = session or requests.Session()
    until = until or date.today()
    url = OPENFDA_BASE + ENFORCEMENT_ENDPOINTS[source_type]
    search = f"report_date:[{since:%Y%m%d} TO {until:%Y%m%d}]"

    results: list[dict] = []
    skip = 0
    while len(results) < max_records and skip <= MAX_SKIP:
        params = {
            "search": search,
            "sort": "report_date:desc",
            "limit": min(PAGE_SIZE, max_records - len(results)),
            "skip": skip,
        }
        if api_key:
            params["api_key"] = api_key

        resp = _get_with_retry(http, url, params, timeout)
        if resp.status_code == 404:  # openFDA's way of saying "no matching records"
            break
        resp.raise_for_status()

        payload = resp.json()
        page = payload.get("results", [])
        total = payload.get("meta", {}).get("results", {}).get("total", 0)
        results.extend(page)
        skip += len(page)
        if not page or skip >= total:
            break

    log.info("Fetched %d %s records since %s", len(results), source_type, since)
    return results


def _parse_date(value: str | None) -> date | None:
    try:
        return datetime.strptime(value, "%Y%m%d").date()
    except (TypeError, ValueError):
        return None


def _shorten(text: str, limit: int = 120) -> str:
    return text if len(text) <= limit else text[: limit - 3].rstrip() + "..."


def normalize_enforcement(raw: dict, source_type: str) -> NormalizedUpdate:
    """Turn one openFDA enforcement record into a NormalizedUpdate."""
    recall_number = raw.get("recall_number")
    if not recall_number:
        raise ValueError("Record has no recall_number")

    classification = raw.get("classification") or "Unclassified"
    firm = raw.get("recalling_firm") or "Unknown firm"
    product = (raw.get("product_description") or "").strip()

    title = f"{classification} recall – {firm}: {_shorten(product)}"[:500]

    # Labelled fields make it easy for the LLM to cite a specific passage later.
    labelled = [
        ("Product", product),
        ("Reason for recall", raw.get("reason_for_recall")),
        ("Classification", classification),
        ("Status", raw.get("status")),
        ("Recalling firm", firm),
        ("Distribution", raw.get("distribution_pattern")),
        ("Code info", raw.get("code_info")),
        ("Recall initiation date", raw.get("recall_initiation_date")),
    ]
    body_text = "\n".join(
        f"{label}: {value.strip()}" for label, value in labelled if value
    )

    endpoint = ENFORCEMENT_ENDPOINTS[source_type]
    url = f"{OPENFDA_BASE}{endpoint}?search=" + quote(
        f'recall_number:"{recall_number}"'
    )

    return NormalizedUpdate(
        source="FDA",
        source_type=source_type,
        source_id=recall_number,
        title=title,
        url=url,
        published_date=_parse_date(raw.get("report_date")),
        body_text=body_text,
        raw=raw,
    )
