"""Draft a labelling impact assessment for an update that has labelling impact.

This is a second, deeper Claude call that runs only on demand. Its output is a starting
point for a labelling team, never a decision: routes are suggestions, and anything that
depends on a company's own labels is raised as an open question.
"""

import argparse
import logging
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, ValidationInfo, field_validator

from regintel.llm.analyze import _unwrap_json_strings, build_user_message
from regintel.llm.citations import quote_in_source
from regintel.llm.claude import call_with_tool
from regintel.llm.schema import LabellingDocument
from regintel.llm.taxonomy import LABELLING_DOCUMENTS
from regintel.portfolio import describe_portfolio

log = logging.getLogger("regintel.assess")

ASSESSMENT_PROMPT_VERSION = "a1"
TOOL_NAME = "record_impact_assessment"

CHANGE_TYPES = ["add", "update", "remove", "review"]
URGENCY = {
    "immediate": "Safety-critical: implement as soon as possible, consider urgent routes.",
    "within_weeks": "Implement in the coming weeks through a dedicated submission.",
    "next_routine_update": "Can be bundled with the next routine labelling update.",
}
REGIONS = ["UK", "EU", "US"]
ROUTES = {
    "UK": [
        "Urgent safety restriction",
        "Type II variation",
        "Type IB variation",
        "No submission needed",
        "To be confirmed",
    ],
    "EU": [
        "Urgent safety restriction",
        "Type II variation",
        "Type IB variation",
        "No submission needed",
        "To be confirmed",
    ],
    "US": [
        "CBE-0 supplement",
        "Prior approval supplement",
        "Annual report",
        "No submission needed",
        "To be confirmed",
    ],
}
ALL_ROUTES = sorted({route for routes in ROUTES.values() for route in routes})

LABEL_SECTIONS = """\
SmPC: 4.1 Therapeutic indications; 4.2 Posology and method of administration; \
4.3 Contraindications; 4.4 Special warnings and precautions for use; 4.5 Interactions; \
4.6 Fertility, pregnancy and lactation; 4.7 Effects on ability to drive and use machines; \
4.8 Undesirable effects; 4.9 Overdose; 5.1 Pharmacodynamic properties; \
5.2 Pharmacokinetic properties; 6.3 Shelf life; 6.4 Special precautions for storage.
PIL: 1 What the medicine is and what it is used for; 2 What you need to know before you \
take it; 3 How to take it; 4 Possible side effects; 5 How to store it; 6 Contents of the \
pack and other information.
US prescribing information: Boxed Warning; 1 Indications and Usage; 2 Dosage and \
Administration; 4 Contraindications; 5 Warnings and Precautions; 6 Adverse Reactions; \
7 Drug Interactions; 8 Use in Specific Populations; 17 Patient Counseling Information; \
Medication Guide."""

Urgency = Literal[tuple(URGENCY)]  # type: ignore[valid-type]
ChangeType = Literal[tuple(CHANGE_TYPES)]  # type: ignore[valid-type]
Region = Literal[tuple(REGIONS)]  # type: ignore[valid-type]
Route = Literal[tuple(ALL_ROUTES)]  # type: ignore[valid-type]


class SectionChange(BaseModel):
    document: LabellingDocument
    section: str = Field(min_length=1)
    change_type: ChangeType
    description: str = Field(min_length=1)
    source_quote: str = Field(min_length=1)


class RouteSuggestion(BaseModel):
    region: Region
    route: Route
    rationale: str = Field(min_length=1)

    @field_validator("route")
    @classmethod
    def route_fits_region(cls, value: str, info: ValidationInfo) -> str:
        region = info.data.get("region")
        if region and value not in ROUTES[region]:
            raise ValueError(f"{value!r} is not a {region} route")
        return value


class WatchlistEffect(BaseModel):
    watchlist_item: str
    why: str = Field(min_length=1)

    @field_validator("watchlist_item")
    @classmethod
    def must_be_on_watchlist(cls, value: str, info: ValidationInfo) -> str:
        allowed = (info.context or {}).get("portfolio")
        if allowed is not None and value not in allowed:
            raise ValueError(f"{value!r} is not on the watchlist")
        return value


class ImpactAssessment(BaseModel):
    scope: str = Field(min_length=1)
    watchlist_effects: list[WatchlistEffect] = Field(default_factory=list, max_length=5)
    urgency: Urgency
    urgency_rationale: str = Field(min_length=1)
    section_changes: list[SectionChange] = Field(min_length=1, max_length=8)
    routes: list[RouteSuggestion] = Field(default_factory=list, max_length=3)
    open_questions: list[str] = Field(default_factory=list, max_length=5)


def _str_list(description: str, max_items: int) -> dict:
    return {
        "type": "array",
        "items": {"type": "string"},
        "maxItems": max_items,
        "description": description,
    }


def build_tool_schema(portfolio: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "description": "One sentence: which products or class are in scope.",
            },
            "watchlist_effects": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "properties": {
                        "watchlist_item": {"type": "string", "enum": portfolio},
                        "why": {"type": "string"},
                    },
                    "required": ["watchlist_item", "why"],
                },
            },
            "urgency": {"type": "string", "enum": list(URGENCY)},
            "urgency_rationale": {"type": "string"},
            "section_changes": {
                "type": "array",
                "minItems": 1,
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "properties": {
                        "document": {
                            "type": "string",
                            "enum": list(LABELLING_DOCUMENTS),
                        },
                        "section": {
                            "type": "string",
                            "description": "Section number and name, e.g. '4.4 Special "
                            "warnings and precautions for use'.",
                        },
                        "change_type": {"type": "string", "enum": CHANGE_TYPES},
                        "description": {
                            "type": "string",
                            "description": "What should change in this section.",
                        },
                        "source_quote": {
                            "type": "string",
                            "description": "Exact passage from the source text "
                            "that requires this change.",
                        },
                    },
                    "required": [
                        "document",
                        "section",
                        "change_type",
                        "description",
                        "source_quote",
                    ],
                },
            },
            "routes": {
                "type": "array",
                "maxItems": 3,
                "items": {
                    "type": "object",
                    "properties": {
                        "region": {"type": "string", "enum": REGIONS},
                        "route": {"type": "string", "enum": ALL_ROUTES},
                        "rationale": {"type": "string"},
                    },
                    "required": ["region", "route", "rationale"],
                },
            },
            "open_questions": _str_list(
                "Company-specific checks the labelling team must make.", 5
            ),
        },
        "required": [
            "scope",
            "watchlist_effects",
            "urgency",
            "urgency_rationale",
            "section_changes",
            "routes",
            "open_questions",
        ],
    }


def build_system_prompt(portfolio: list[dict]) -> str:
    routes = "\n".join(f"- {region}: {', '.join(r)}" for region, r in ROUTES.items())
    urgency = "\n".join(f"- {k}: {v}" for k, v in URGENCY.items())
    return f"""You are a labelling specialist preparing a DRAFT labelling impact \
assessment for a regulatory affairs team. You read one official FDA or MHRA update that has \
already been flagged as having labelling impact, and record the assessment by calling the \
{TOOL_NAME} tool.

Rules:
- Base every section change on the source text. Each change needs a source_quote copied \
exactly, character for character, from the source text, stating what requires the change.
- You do not know the company's current labels. Never claim what a label currently says. \
Describe what the section should contain or be checked for, and put anything that depends on \
the company's own labels or core data sheet into open_questions.
- Use standard section names:
{LABEL_SECTIONS}
- Pair SmPC changes with the matching PIL section where patients are affected, and include US \
prescribing information only if the update concerns a product or class marketed in the US.
- Routes are suggestions for the team to confirm. Use "To be confirmed" when the source does \
not give enough to judge. Allowed routes:
{routes}
- Urgency:
{urgency}

Watchlist (record an effect only if the update clearly concerns the item or its class):
{describe_portfolio(portfolio)}"""


def build_assessment_message(
    title: str, source: str, source_type: str, body_text: str, labels: dict
) -> str:
    context = (
        f"Triage labels already assigned: relevance {labels.get('relevance')}, topic "
        f"{labels.get('topic')}, documents flagged {labels.get('labelling_documents') or []}."
    )
    return f"{context}\n\n{build_user_message(title, source, source_type, body_text)}"


class AssessmentError(Exception):
    """Raised when the assessment output can't be used."""


@dataclass
class AssessmentResult:
    assessment: ImpactAssessment
    content: dict  # the assessment as stored, with a `supported` flag on each change
    model: str
    prompt_version: str = ASSESSMENT_PROMPT_VERSION

    @property
    def all_citations_supported(self) -> bool:
        return all(c["supported"] for c in self.content["section_changes"])


def draft_assessment(
    client,
    model: str,
    *,
    title: str,
    source: str,
    source_type: str,
    body_text: str,
    labels: dict,
    portfolio: list[dict],
) -> AssessmentResult:
    names = [item["name"] for item in portfolio]
    response = call_with_tool(
        client,
        model=model,
        max_tokens=3000,
        system=build_system_prompt(portfolio),
        tool={
            "name": TOOL_NAME,
            "description": "Record the draft labelling impact assessment.",
            "input_schema": build_tool_schema(names),
        },
        messages=[
            {
                "role": "user",
                "content": build_assessment_message(
                    title, source, source_type, body_text, labels
                ),
            }
        ],
    )
    tool_input = next((b.input for b in response.content if b.type == "tool_use"), None)
    if tool_input is None:
        raise AssessmentError("Claude did not return a tool call")
    list_fields = ("watchlist_effects", "section_changes", "routes", "open_questions")
    try:
        assessment = ImpactAssessment.model_validate(
            _unwrap_json_strings(tool_input, list_fields), context={"portfolio": names}
        )
    except ValidationError as exc:
        raise AssessmentError(f"Output failed validation: {exc}") from exc

    content = assessment.model_dump()
    for change in content["section_changes"]:
        change["supported"] = quote_in_source(change["source_quote"], body_text)
    return AssessmentResult(assessment=assessment, content=content, model=model)


def main(argv: list[str] | None = None) -> None:
    """Draft assessments in bulk for analysed updates with labelling impact."""
    import anthropic

    from regintel import config
    from regintel.api.queries import UpdateFilters, filtered_rows, final_labels
    from regintel.db.database import get_engine, get_sessionmaker, init_db
    from regintel.db.repository import latest_assessment, save_assessment
    from regintel.portfolio import load_portfolio

    parser = argparse.ArgumentParser(description="Draft labelling impact assessments")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--model", default=config.ASSESSMENT_MODEL)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    if not config.ANTHROPIC_API_KEY:
        raise SystemExit("ANTHROPIC_API_KEY is not set. Add it to your .env file.")

    engine = get_engine()
    init_db(engine)
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    portfolio = load_portfolio()
    done = failed = 0
    with get_sessionmaker(engine)() as session:
        _, rows = filtered_rows(session, UpdateFilters(labelling_impact=True))
        for update, analysis in rows:
            if done >= args.limit:
                break
            if latest_assessment(session, analysis.id) is not None:
                continue
            try:
                result = draft_assessment(
                    client,
                    args.model,
                    title=update.title,
                    source=update.source,
                    source_type=update.source_type,
                    body_text=update.body_text,
                    labels=final_labels(analysis),
                    portfolio=portfolio,
                )
            except (AssessmentError, anthropic.APIError) as exc:
                log.warning("Update %s failed: %s", update.id, exc)
                failed += 1
                continue
            save_assessment(session, analysis, result)
            done += 1
            log.info(
                "Update %s: %s, %d section changes",
                update.id,
                result.assessment.urgency,
                len(result.assessment.section_changes),
            )
    log.info("Done: drafted %d, failed %d", done, failed)


if __name__ == "__main__":
    main()
