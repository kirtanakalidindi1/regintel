from datetime import date

import pytest

from regintel.ingest import mhra
from regintel.ingest.html_text import html_to_text

SEARCH_RESULT = {
    "title": "Valproate: new safety measures for men",
    "description": "Healthcare professionals should advise male patients about potential risks.",
    "link": "/drug-safety-update/valproate-new-safety-measures",
    "public_timestamp": "2026-10-20T09:30:00.000+01:00",
    "content_store_document_type": "drug_safety_update",
}

CONTENT = {
    "details": {
        "body": "<h2>Advice for healthcare professionals</h2>"
        "<ul><li>Discuss the potential risk with male patients.</li>"
        "<li>Consider alternative treatments.</li></ul>"
        "<p>Report suspected reactions via the <a href='#'>Yellow Card scheme</a>.</p>",
        "metadata": {"therapeutic_area": ["neurology", "psychiatry"]},
    }
}


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


class FakeSession:
    """Routes search and content requests to canned responses."""

    def __init__(self, search_pages, content_by_link=None):
        self.search_pages = list(search_pages)
        self.content_by_link = content_by_link or {}
        self.search_calls = []

    def get(self, url, params=None, timeout=None):
        if url == mhra.SEARCH_URL:
            self.search_calls.append(params)
            return self.search_pages.pop(0)
        link = url.removeprefix(mhra.CONTENT_URL)
        if link in self.content_by_link:
            return FakeResponse(200, self.content_by_link[link])
        return FakeResponse(404)


def search_page(results, total):
    return FakeResponse(200, {"results": results, "total": total})


def test_html_to_text_keeps_structure():
    text = html_to_text(CONTENT["details"]["body"])
    assert text.splitlines() == [
        "## Advice for healthcare professionals",
        "- Discuss the potential risk with male patients.",
        "- Consider alternative treatments.",
        "Report suspected reactions via the Yellow Card scheme.",
    ]


def test_normalize_item_combines_summary_and_body():
    rec = mhra.normalize_item(SEARCH_RESULT, CONTENT)
    assert rec.source == "MHRA"
    assert rec.source_type == "drug_safety_update"
    assert rec.source_id == SEARCH_RESULT["link"]
    assert rec.url == "https://www.gov.uk" + SEARCH_RESULT["link"]
    assert rec.published_date == date(2026, 10, 20)
    assert rec.body_text.startswith("Summary: Healthcare professionals should advise")
    assert "- Consider alternative treatments." in rec.body_text
    assert rec.raw["metadata"]["therapeutic_area"] == ["neurology", "psychiatry"]


def test_normalize_item_handles_list_style_body():
    content = {
        "details": {
            "body": [
                {"content_type": "text/govspeak", "content": "ignored"},
                {"content_type": "text/html", "content": "<p>Recall of batch 123.</p>"},
            ]
        }
    }
    rec = mhra.normalize_item(SEARCH_RESULT, content)
    assert "Recall of batch 123." in rec.body_text
    assert "ignored" not in rec.body_text


def test_normalize_item_requires_link():
    with pytest.raises(ValueError):
        mhra.normalize_item({**SEARCH_RESULT, "link": None}, CONTENT)


def test_search_paginates_and_sends_filters():
    session = FakeSession(
        [
            search_page([{"link": f"/a/{i}"} for i in range(100)], 130),
            search_page([{"link": f"/b/{i}"} for i in range(30)], 130),
        ]
    )
    results = mhra.search_items(
        "medical_safety_alert",
        date(2026, 10, 1),
        until=date(2026, 10, 31),
        session=session,
    )
    assert len(results) == 130
    first = session.search_calls[0]
    assert first["filter_content_store_document_type"] == "medical_safety_alert"
    assert first["filter_public_timestamp"] == "from:2026-10-01,to:2026-10-31"
    assert [c["start"] for c in session.search_calls] == [0, 100]


def test_fetch_and_normalize_skips_items_whose_content_fails():
    ok = SEARCH_RESULT
    broken = {**SEARCH_RESULT, "link": "/drug-safety-update/missing"}
    session = FakeSession([search_page([ok, broken], 2)], {ok["link"]: CONTENT})
    records = mhra.fetch_and_normalize(
        "drug_safety_update", date(2026, 10, 1), session=session, delay=0
    )
    assert [r.source_id for r in records] == [ok["link"]]


def test_unknown_document_type_raises():
    with pytest.raises(ValueError):
        mhra.search_items("news_story", date(2026, 10, 1), session=FakeSession([]))
