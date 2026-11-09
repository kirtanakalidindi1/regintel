from types import SimpleNamespace

import pytest

from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.models import AnalysisRecord, Update
from regintel.db.repository import updates_needing_analysis, upsert_updates
from regintel.ingest import fda
from regintel.llm import run as llm_run
from regintel.llm.analyze import PROMPT_VERSION, AnalysisError, analyze_update
from tests.test_fda import SAMPLE

GOOD_OUTPUT = {
    "topic": "recall",
    "product_type": "medicine",
    "therapeutic_areas": ["infectious_disease"],
    "relevance": "medium",
    "relevance_rationale": "Class II recall for a quality defect.",
    "summary_points": [
        {
            "claim": "Amoxicillin capsules are being recalled.",
            "quote": "Amoxicillin Capsules USP, 500 mg",
        },
        {
            "claim": "The capsules failed dissolution testing.",
            "quote": "Failed dissolution specifications.",
        },
    ],
}


class FakeClient:
    """Mimics anthropic.Anthropic().messages.create returning a tool_use block."""

    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []
        self.messages = self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        out = self.outputs.pop(0)
        content = (
            [SimpleNamespace(type="tool_use", input=out)]
            if out is not None
            else [SimpleNamespace(type="text", text="I can't do that.")]
        )
        return SimpleNamespace(content=content)


def body():
    return fda.normalize_enforcement(SAMPLE, "drug_enforcement").body_text


def analyze(client):
    return analyze_update(
        client,
        "test-model",
        title="t",
        source="FDA",
        source_type="drug_enforcement",
        body_text=body(),
    )


def test_good_output_is_validated_and_citations_checked():
    result = analyze(FakeClient([GOOD_OUTPUT]))
    assert result.analysis.topic == "recall"
    assert result.all_citations_supported


def test_request_forces_the_tool_and_includes_source():
    client = FakeClient([GOOD_OUTPUT])
    analyze(client)
    call = client.calls[0]
    assert call["tool_choice"] == {"type": "tool", "name": "record_analysis"}
    assert "Failed dissolution specifications." in call["messages"][0]["content"]


def test_unsupported_quote_is_flagged():
    bad = {
        **GOOD_OUTPUT,
        "summary_points": [{"claim": "x", "quote": "Patients have died."}],
    }
    result = analyze(FakeClient([bad]))
    assert not result.all_citations_supported


def test_label_outside_taxonomy_is_rejected():
    with pytest.raises(AnalysisError):
        analyze(FakeClient([{**GOOD_OUTPUT, "topic": "breaking_news"}]))


def test_missing_tool_call_is_rejected():
    with pytest.raises(AnalysisError):
        analyze(FakeClient([None]))


@pytest.fixture
def session():
    engine = get_engine("sqlite://")
    init_db(engine)
    with get_sessionmaker(engine)() as s:
        yield s


def test_run_saves_analysis_and_skips_already_analyzed(session):
    upsert_updates(session, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
    counts = llm_run.run(session, FakeClient([GOOD_OUTPUT]), "test-model", limit=10)
    assert counts == {"analyzed": 1, "failed": 0, "citations_all_supported": 1}
    stored = session.query(AnalysisRecord).one()
    assert stored.review_status == "pending"
    assert updates_needing_analysis(session, PROMPT_VERSION, 10) == []


def test_changed_update_needs_reanalysis(session):
    upsert_updates(session, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
    llm_run.run(session, FakeClient([GOOD_OUTPUT]), "test-model", limit=10)
    upsert_updates(
        session,
        [
            fda.normalize_enforcement(
                {**SAMPLE, "status": "Terminated"}, "drug_enforcement"
            )
        ],
    )
    pending = updates_needing_analysis(session, PROMPT_VERSION, 10)
    assert [u.source_id for u in pending] == [session.query(Update).one().source_id]


def test_failed_analysis_is_counted_not_saved(session):
    upsert_updates(session, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
    counts = llm_run.run(session, FakeClient([None]), "test-model", limit=10)
    assert counts["failed"] == 1
    assert session.query(AnalysisRecord).count() == 0
