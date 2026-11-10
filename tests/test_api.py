import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from regintel.api.main import create_app
from regintel.db.database import get_sessionmaker, init_db
from regintel.db.models import Update
from regintel.db.repository import save_analysis, upsert_updates
from regintel.ingest import fda, mhra
from regintel.llm.analyze import AnalysisResult
from regintel.llm.schema import Analysis
from tests.test_analyze import GOOD_OUTPUT, FakeClient
from tests.test_assess import GOOD_ASSESSMENT
from tests.test_fda import SAMPLE
from tests.test_mhra import CONTENT, SEARCH_RESULT


@pytest.fixture
def fake_claude():
    return FakeClient([GOOD_ASSESSMENT])


@pytest.fixture
def client(fake_claude):
    # One shared in-memory database that the test client's threads can all use
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with get_sessionmaker(engine)() as s:
        upsert_updates(
            s,
            [
                fda.normalize_enforcement(SAMPLE, "drug_enforcement"),
                mhra.normalize_item(SEARCH_RESULT, CONTENT),
            ],
        )
        recall = s.query(Update).filter_by(source="FDA").one()
        result = AnalysisResult(
            analysis=Analysis.model_validate(GOOD_OUTPUT),
            summary_points=[
                {**p, "supported": True} for p in GOOD_OUTPUT["summary_points"]
            ],
            model="test-model",
        )
        save_analysis(s, recall, result)
    return TestClient(create_app(engine, llm_client=fake_claude))


def fda_id(client):
    return client.get("/updates", params={"source": "FDA"}).json()["items"][0]["id"]


def test_health_and_taxonomy(client):
    assert client.get("/health").json() == {"status": "ok"}
    tax = client.get("/taxonomy").json()
    assert "recall" in tax["topics"] and "high" in tax["relevance"]


def test_stats(client):
    stats = client.get("/stats").json()
    assert stats["updates"] == 2
    assert stats["analysed_updates"] == 1
    assert stats["by_review_status"] == {"pending": 1}
    assert stats["queues"] == {
        "needs_review": 1,
        "high_relevance": 0,
        "labelling_impact": 0,
        "portfolio_matches": 1,
    }


def test_portfolio_endpoint_lists_watchlist(client):
    names = [item["name"] for item in client.get("/portfolio").json()]
    assert "PARP inhibitors" in names and "Complement C5 inhibitors" in names


def test_labelling_correction_moves_update_into_queue(client):
    analysis_id = client.get(f"/updates/{fda_id(client)}").json()["analysis"]["id"]
    resp = client.post(
        f"/analyses/{analysis_id}/review",
        json={
            "status": "corrected",
            "corrections": {"labelling_impact": True},
        },
    )
    assert resp.status_code == 200
    assert (
        client.get("/updates", params={"labelling_impact": True}).json()["total"] == 1
    )
    assert client.get("/stats").json()["queues"]["labelling_impact"] == 1


def test_list_shows_labels_for_analysed_updates(client):
    data = client.get("/updates").json()
    assert data["total"] == 2
    by_source = {item["source"]: item for item in data["items"]}
    assert by_source["FDA"]["topic"] == "recall"
    assert by_source["MHRA"]["topic"] is None


@pytest.mark.parametrize(
    "params, expected",
    [
        ({"source": "MHRA"}, 1),
        ({"topic": "recall"}, 1),
        ({"therapeutic_area": "infectious_disease"}, 1),
        ({"therapeutic_area": "oncology"}, 0),
        ({"q": "dissolution"}, 1),
        ({"q": "VALPROATE"}, 1),
        ({"analysed": False}, 1),
        ({"review_status": "pending"}, 1),
        ({"portfolio_item": "Penicillins"}, 1),
        ({"portfolio_item": "PARP inhibitors"}, 0),
        ({"labelling_impact": False}, 1),
        ({"labelling_impact": True}, 0),
        ({"action_owner": "quality_supply"}, 1),
        ({"rare_disease": True}, 0),
        ({"date_from": "2026-10-21", "date_to": "2026-10-21"}, 1),
    ],
)
def test_filters(client, params, expected):
    assert client.get("/updates", params=params).json()["total"] == expected


def test_detail_includes_analysis_and_body(client):
    detail = client.get(f"/updates/{fda_id(client)}").json()
    assert "Failed dissolution" in detail["body_text"]
    assert detail["analysis"]["relevance"] == "medium"


def test_missing_update_is_404(client):
    assert client.get("/updates/9999").status_code == 404


def test_approve(client):
    analysis_id = client.get(f"/updates/{fda_id(client)}").json()["analysis"]["id"]
    resp = client.post(f"/analyses/{analysis_id}/review", json={"status": "approved"})
    assert resp.status_code == 200
    assert resp.json()["review_status"] == "approved"
    assert resp.json()["reviewed_at"] is not None


def test_correction_overrides_labels_in_list_and_export(client):
    analysis_id = client.get(f"/updates/{fda_id(client)}").json()["analysis"]["id"]
    resp = client.post(
        f"/analyses/{analysis_id}/review",
        json={
            "status": "corrected",
            "corrections": {"relevance": "high"},
            "note": "Antibiotic supply impact makes this urgent.",
        },
    )
    assert resp.status_code == 200
    item = client.get("/updates", params={"source": "FDA"}).json()["items"][0]
    assert item["relevance"] == "high"
    exported = client.get("/export", params={"format": "json", "source": "FDA"}).json()
    assert exported[0]["relevance"] == "high"
    assert exported[0]["review_status"] == "corrected"


@pytest.mark.parametrize(
    "body",
    [
        {"status": "corrected"},  # no corrections
        {
            "status": "approved",
            "corrections": {"topic": "recall"},
        },  # corrections without corrected
        {
            "status": "corrected",
            "corrections": {"topic": "not_a_topic"},
        },  # outside taxonomy
        {"status": "maybe"},
    ],
)
def test_invalid_reviews_are_rejected(client, body):
    analysis_id = client.get(f"/updates/{fda_id(client)}").json()["analysis"]["id"]
    assert client.post(f"/analyses/{analysis_id}/review", json=body).status_code == 422


def test_csv_export(client):
    resp = client.get("/export")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    lines = resp.text.strip().splitlines()
    assert lines[0].startswith("id,source,source_type")
    assert "labelling_impact" in lines[0] and "watchlist_matches" in lines[0]
    assert len(lines) == 3  # header + 2 updates


def analysis_id(client):
    return client.get(f"/updates/{fda_id(client)}").json()["analysis"]["id"]


def test_assessment_lifecycle(client):
    aid = analysis_id(client)
    assert client.get(f"/analyses/{aid}/assessment").status_code == 404

    created = client.post(f"/analyses/{aid}/assessment")
    assert created.status_code == 200
    body = created.json()
    assert body["status"] == "draft"
    assert body["content"]["urgency"] == "within_weeks"

    detail = client.get(f"/updates/{fda_id(client)}").json()
    assert detail["assessment"]["id"] == body["id"]

    reviewed = client.post(
        f"/assessments/{body['id']}/review",
        json={"status": "accepted", "note": "Good starting point."},
    )
    assert reviewed.json()["status"] == "accepted"

    md = client.get(f"/assessments/{body['id']}/export")
    assert md.headers["content-type"].startswith("text/markdown")
    assert "## Section changes" in md.text and "Good starting point." in md.text


def test_assessment_for_missing_analysis_is_404(client):
    assert client.post("/analyses/9999/assessment").status_code == 404
    assert client.get("/assessments/9999/export").status_code == 404


def test_assessment_needs_api_key_without_injected_client(monkeypatch):
    from regintel import config

    monkeypatch.setattr(config, "ANTHROPIC_API_KEY", None)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with get_sessionmaker(engine)() as s:
        upsert_updates(s, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
        save_analysis(
            s,
            s.query(Update).one(),
            AnalysisResult(
                analysis=Analysis.model_validate(GOOD_OUTPUT),
                summary_points=[
                    {**p, "supported": True} for p in GOOD_OUTPUT["summary_points"]
                ],
                model="test-model",
            ),
        )
    bare = TestClient(create_app(engine))
    assert bare.post("/analyses/1/assessment").status_code == 503


def test_claude_api_errors_become_a_clear_502():
    import anthropic
    import httpx

    class FailingClient:
        def __init__(self):
            self.messages = self

        def create(self, **kwargs):
            response = httpx.Response(529, request=httpx.Request("POST", "https://api"))
            raise anthropic.APIStatusError("Overloaded", response=response, body=None)

    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    init_db(engine)
    with get_sessionmaker(engine)() as s:
        upsert_updates(s, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
        save_analysis(
            s,
            s.query(Update).one(),
            AnalysisResult(
                analysis=Analysis.model_validate(GOOD_OUTPUT),
                summary_points=[
                    {**p, "supported": True} for p in GOOD_OUTPUT["summary_points"]
                ],
                model="test-model",
            ),
        )
    resp = TestClient(create_app(engine, llm_client=FailingClient())).post(
        "/analyses/1/assessment"
    )
    assert resp.status_code == 502
    assert "The Claude API returned an error" in resp.json()["detail"]
