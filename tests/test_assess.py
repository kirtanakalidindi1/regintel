import json
from types import SimpleNamespace

import pytest

from regintel.assessment_export import to_markdown
from regintel.ingest import mhra
from regintel.llm.assess import AssessmentError, draft_assessment
from tests.test_analyze import TEST_PORTFOLIO, FakeClient
from tests.test_mhra import CONTENT, SEARCH_RESULT

GOOD_ASSESSMENT = {
    "scope": "All valproate-containing products.",
    "watchlist_effects": [],
    "urgency": "within_weeks",
    "urgency_rationale": "New risk communication for male patients requires label updates.",
    "section_changes": [
        {
            "document": "smpc",
            "section": "4.4 Special warnings and precautions for use",
            "change_type": "add",
            "description": "Add advice to discuss the potential risk with male patients.",
            "source_quote": "Discuss the potential risk with male patients.",
        },
        {
            "document": "pil",
            "section": "2 What you need to know before you take it",
            "change_type": "add",
            "description": "Explain the risk in patient-friendly language.",
            "source_quote": "Healthcare professionals should advise male patients",
        },
    ],
    "routes": [
        {
            "region": "UK",
            "route": "Type II variation",
            "rationale": "New safety information.",
        }
    ],
    "open_questions": [
        "Does the company core data sheet already include this warning?"
    ],
}


def body():
    return mhra.normalize_item(SEARCH_RESULT, CONTENT).body_text


def draft(client):
    return draft_assessment(
        client,
        "test-model",
        title="Valproate",
        source="MHRA",
        source_type="drug_safety_update",
        body_text=body(),
        labels={
            "relevance": "medium",
            "topic": "safety_communication",
            "labelling_documents": ["smpc", "pil"],
        },
        portfolio=TEST_PORTFOLIO,
    )


def test_good_assessment_is_validated_and_quotes_checked():
    result = draft(FakeClient([GOOD_ASSESSMENT]))
    assert result.assessment.urgency == "within_weeks"
    assert [c["supported"] for c in result.content["section_changes"]] == [True, True]
    assert result.all_citations_supported


def test_request_includes_section_names_and_triage_labels():
    client = FakeClient([GOOD_ASSESSMENT])
    draft(client)
    call = client.calls[0]
    assert "4.4 Special warnings and precautions for use" in call["system"]
    assert "CBE-0 supplement" in call["system"]
    assert "documents flagged ['smpc', 'pil']" in call["messages"][0]["content"]


def test_unsupported_quote_is_flagged():
    bad = json.loads(json.dumps(GOOD_ASSESSMENT))
    bad["section_changes"][0]["source_quote"] = "Contraindicated in pregnancy."
    result = draft(FakeClient([bad]))
    assert not result.all_citations_supported


def test_route_must_belong_to_its_region():
    bad = {
        **GOOD_ASSESSMENT,
        "routes": [{"region": "UK", "route": "CBE-0 supplement", "rationale": "x"}],
    }
    with pytest.raises(AssessmentError):
        draft(FakeClient([bad]))


def test_watchlist_item_must_exist():
    bad = {
        **GOOD_ASSESSMENT,
        "watchlist_effects": [{"watchlist_item": "Statins", "why": "x"}],
    }
    with pytest.raises(AssessmentError):
        draft(FakeClient([bad]))


def test_stringified_lists_are_decoded():
    out = {**GOOD_ASSESSMENT, "open_questions": "[]</open_questions>"}
    assert draft(FakeClient([out])).assessment.open_questions == []


def test_markdown_export_has_table_disclaimer_and_questions():
    result = draft(FakeClient([GOOD_ASSESSMENT]))
    update = SimpleNamespace(
        title="Valproate",
        source="MHRA",
        source_type="drug_safety_update",
        url="https://www.gov.uk/x",
        published_date="2026-10-20",
    )
    analysis = SimpleNamespace(prompt_version="v3")
    record = SimpleNamespace(
        content=result.content,
        model="test-model",
        prompt_version="a1",
        created_at=__import__("datetime").datetime(2026, 11, 10),
        status="draft",
        reviewer_note=None,
    )
    md = to_markdown(update, analysis, record)
    assert md.startswith("# Draft labelling impact assessment: Valproate")
    assert "| Summary of Product Characteristics | 4.4 Special warnings" in md
    assert "Routes are suggestions" in md
    assert "- Does the company core data sheet already include this warning?" in md


class RejectsForcedToolClient(FakeClient):
    """Behaves like a model that only accepts tool_choice 'auto'."""

    def create(self, **kwargs):
        if kwargs["tool_choice"]["type"] == "tool":
            import anthropic
            import httpx

            self.calls.append(kwargs)
            response = httpx.Response(400, request=httpx.Request("POST", "https://api"))
            raise anthropic.BadRequestError(
                'tool_choice: type "tool" and "any" are not supported for this model.',
                response=response,
                body=None,
            )
        return super().create(**kwargs)


def test_falls_back_to_auto_tool_choice_when_forced_is_rejected():
    from regintel.llm import claude

    claude._FORCED_TOOL_UNSUPPORTED.discard("test-model")
    client = RejectsForcedToolClient([GOOD_ASSESSMENT, GOOD_ASSESSMENT])
    assert draft(client).assessment.urgency == "within_weeks"
    assert [c["tool_choice"]["type"] for c in client.calls] == ["tool", "auto"]
    assert (
        "Respond only by calling the record_impact_assessment tool"
        in client.calls[1]["system"]
    )

    # The model is remembered, so the next call goes straight to auto
    draft(client)
    assert [c["tool_choice"]["type"] for c in client.calls] == ["tool", "auto", "auto"]
    claude._FORCED_TOOL_UNSUPPORTED.discard("test-model")


def test_other_bad_requests_are_not_swallowed():
    import anthropic
    import httpx

    class BrokenClient(FakeClient):
        def create(self, **kwargs):
            response = httpx.Response(400, request=httpx.Request("POST", "https://api"))
            raise anthropic.BadRequestError(
                "max_tokens too large", response=response, body=None
            )

    with pytest.raises(anthropic.BadRequestError):
        draft(BrokenClient([]))
