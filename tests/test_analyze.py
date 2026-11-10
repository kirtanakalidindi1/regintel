from types import SimpleNamespace

import pytest

from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.models import AnalysisRecord, Update
from regintel.db.repository import updates_needing_analysis, upsert_updates
from regintel.ingest import fda
from regintel.llm import run as llm_run
from regintel.llm.analyze import PROMPT_VERSION, AnalysisError, analyze_update
from tests.test_fda import SAMPLE

TEST_PORTFOLIO = [
    {"name": "PARP inhibitors", "area": "oncology", "examples": ["olaparib"]},
    {"name": "Penicillins", "area": "infectious disease", "examples": ["amoxicillin"]},
]

GOOD_OUTPUT = {
    "topic": "recall",
    "product_type": "medicine",
    "therapeutic_areas": ["infectious_disease"],
    "rare_disease": False,
    "relevance": "medium",
    "relevance_rationale": "Class II recall for a quality defect.",
    "labelling_impact": False,
    "labelling_documents": [],
    "action_owners": ["quality_supply"],
    "portfolio_impacts": [
        {
            "watchlist_item": "Penicillins",
            "reason": "Amoxicillin capsules are recalled.",
        }
    ],
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
        portfolio=TEST_PORTFOLIO,
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


def test_list_returned_as_json_string_is_decoded():
    import json

    stringified = {
        **GOOD_OUTPUT,
        "summary_points": json.dumps(GOOD_OUTPUT["summary_points"]),
    }
    result = analyze(FakeClient([stringified]))
    assert len(result.summary_points) == 2
    assert result.all_citations_supported


def test_list_with_stray_closing_tag_is_decoded():
    out = {**GOOD_OUTPUT, "portfolio_impacts": "[]</portfolio_impacts>"}
    assert analyze(FakeClient([out])).analysis.portfolio_impacts == []


def test_unparseable_string_is_still_rejected():
    with pytest.raises(AnalysisError):
        analyze(FakeClient([{**GOOD_OUTPUT, "summary_points": "not json"}]))


def test_watchlist_and_prompt_reach_the_request():
    client = FakeClient([GOOD_OUTPUT])
    analyze(client)
    call = client.calls[0]
    assert "PARP inhibitors" in call["system"] and "olaparib" in call["system"]
    item_enum = call["tools"][0]["input_schema"]["properties"]["portfolio_impacts"][
        "items"
    ]
    assert item_enum["properties"]["watchlist_item"]["enum"] == [
        "PARP inhibitors",
        "Penicillins",
    ]


def test_unknown_watchlist_item_is_rejected():
    bad = {
        **GOOD_OUTPUT,
        "portfolio_impacts": [{"watchlist_item": "Statins", "reason": "x"}],
    }
    with pytest.raises(AnalysisError):
        analyze(FakeClient([bad]))


def test_documents_cleared_when_no_labelling_impact():
    out = {**GOOD_OUTPUT, "labelling_impact": False, "labelling_documents": ["smpc"]}
    assert analyze(FakeClient([out])).analysis.labelling_documents == []


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
    counts = llm_run.run(
        session,
        FakeClient([GOOD_OUTPUT]),
        "test-model",
        limit=10,
        portfolio=TEST_PORTFOLIO,
    )
    assert counts == {"analyzed": 1, "failed": 0, "citations_all_supported": 1}
    stored = session.query(AnalysisRecord).one()
    assert stored.review_status == "pending"
    assert stored.action_owners == ["quality_supply"]
    assert stored.portfolio_impacts[0]["watchlist_item"] == "Penicillins"
    assert updates_needing_analysis(session, PROMPT_VERSION, 10) == []


def test_changed_update_needs_reanalysis(session):
    upsert_updates(session, [fda.normalize_enforcement(SAMPLE, "drug_enforcement")])
    llm_run.run(
        session,
        FakeClient([GOOD_OUTPUT]),
        "test-model",
        limit=10,
        portfolio=TEST_PORTFOLIO,
    )
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
    counts = llm_run.run(
        session, FakeClient([None]), "test-model", limit=10, portfolio=TEST_PORTFOLIO
    )
    assert counts["failed"] == 1
    assert session.query(AnalysisRecord).count() == 0
