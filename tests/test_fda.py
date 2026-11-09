from datetime import date

import pytest

from regintel.ingest import fda

SAMPLE = {
    "recall_number": "D-0123-2026",
    "classification": "Class II",
    "recalling_firm": "Example Pharma Inc.",
    "product_description": "Amoxicillin Capsules USP, 500 mg, 100-count bottle",
    "reason_for_recall": "Failed dissolution specifications.",
    "status": "Ongoing",
    "distribution_pattern": "Nationwide in the USA",
    "report_date": "20261021",
    "recall_initiation_date": "20261002",
}


class FakeResponse:
    def __init__(self, status_code, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    """Stands in for requests.Session so tests never touch the network."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append(params)
        return self.responses.pop(0)


def page(records, total):
    return FakeResponse(
        200, {"meta": {"results": {"total": total}}, "results": records}
    )


def test_normalize_builds_expected_fields():
    rec = fda.normalize_enforcement(SAMPLE, "drug_enforcement")
    assert rec.source == "FDA"
    assert rec.source_id == "D-0123-2026"
    assert rec.published_date == date(2026, 10, 21)
    assert rec.title.startswith("Class II recall – Example Pharma Inc.")
    assert "Reason for recall: Failed dissolution specifications." in rec.body_text
    assert "recall_number" in rec.url and "D-0123-2026" in rec.url


def test_normalize_rejects_missing_recall_number():
    with pytest.raises(ValueError):
        fda.normalize_enforcement({**SAMPLE, "recall_number": None}, "drug_enforcement")


def test_bad_date_becomes_none():
    rec = fda.normalize_enforcement(
        {**SAMPLE, "report_date": "not-a-date"}, "drug_enforcement"
    )
    assert rec.published_date is None


def test_content_hash_changes_when_record_changes():
    a = fda.normalize_enforcement(SAMPLE, "drug_enforcement")
    b = fda.normalize_enforcement(
        {**SAMPLE, "status": "Terminated"}, "drug_enforcement"
    )
    assert a.content_hash != b.content_hash


def test_fetch_paginates_until_total_reached():
    session = FakeSession(
        [
            page([{"id": i} for i in range(100)], 150),
            page([{"id": i} for i in range(50)], 150),
        ]
    )
    results = fda.fetch_enforcement(
        "drug_enforcement", date(2026, 10, 1), session=session
    )
    assert len(results) == 150
    assert [c["skip"] for c in session.calls] == [0, 100]


def test_fetch_respects_max_records():
    session = FakeSession([page([{"id": i} for i in range(20)], 500)])
    results = fda.fetch_enforcement(
        "drug_enforcement", date(2026, 10, 1), max_records=20, session=session
    )
    assert len(results) == 20
    assert session.calls[0]["limit"] == 20


def test_fetch_returns_empty_on_404():
    session = FakeSession([FakeResponse(404)])
    assert (
        fda.fetch_enforcement("drug_enforcement", date(2026, 10, 1), session=session)
        == []
    )


def test_unknown_source_type_raises():
    with pytest.raises(ValueError):
        fda.fetch_enforcement(
            "food_enforcement", date(2026, 10, 1), session=FakeSession([])
        )
