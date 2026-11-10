"""Ask Claude for a structured, source-grounded analysis of one regulatory update."""

import json
import re
from dataclasses import dataclass

from pydantic import ValidationError

from regintel.llm.citations import verify_points
from regintel.llm.claude import call_with_tool
from regintel.llm.schema import TOOL_NAME, Analysis, build_tool_schema
from regintel.llm.taxonomy import (
    ACTION_OWNERS,
    LABELLING_DOCUMENTS,
    PRODUCT_TYPES,
    RELEVANCE,
    RELEVANCE_RULES,
    THERAPEUTIC_AREAS,
    TOPICS,
    describe,
)
from regintel.portfolio import describe_portfolio

PROMPT_VERSION = "v3"
MAX_SOURCE_CHARS = 30_000


def build_system_prompt(portfolio: list[dict]) -> str:
    return f"""You are a regulatory intelligence analyst supporting regulatory affairs and \
labelling teams. You read one official FDA or MHRA update and record a structured analysis by \
calling the {TOOL_NAME} tool.

Rules:
- Use only the source text you are given. Do not add facts from outside knowledge, except to \
recognise which drug class a named product belongs to.
- Every summary point needs a quote copied exactly, character for character, from the source \
text. Keep quotes short (one sentence or less) and do not paraphrase inside a quote.
- A quote must be a sentence or phrase that actually states the fact in the claim. Never use a \
heading, title or label on its own as a quote.
- Write 2 to 5 summary points covering: what product is affected, what the issue is, and what \
action is required and by whom.
- If the document is a digest listing several notices, summarise the most safety-critical items.
- Choose labels only from the lists below.

Topics:
{describe(TOPICS)}

Product types:
{describe(PRODUCT_TYPES)}

Therapeutic areas (pick 1 to 3): {", ".join(THERAPEUTIC_AREAS)}

Relevance:
{describe(RELEVANCE)}
{RELEVANCE_RULES}

Labelling impact: true when the update requires, or is likely to prompt, changes to product \
information (new warnings, contraindications, dosing, monitoring or corrections), including \
class-wide changes that other products in the same class would need to assess. Recalls for \
quality defects alone do not have labelling impact.
Labelling documents:
{describe(LABELLING_DOCUMENTS)}

Action owners (pick 1 to 4):
{describe(ACTION_OWNERS)}

Watchlist. Add a portfolio impact only when the update concerns a listed product or class, or \
a class-wide change clearly applies to it. Most updates match nothing; leave the list empty \
rather than guess.
{describe_portfolio(portfolio)}"""


class AnalysisError(Exception):
    """Raised when Claude's output can't be used."""


@dataclass
class AnalysisResult:
    analysis: Analysis
    summary_points: list[dict]  # each with claim, quote, supported
    model: str
    prompt_version: str = PROMPT_VERSION

    @property
    def all_citations_supported(self) -> bool:
        return all(p["supported"] for p in self.summary_points)


_STRAY_TAGS = re.compile(r"</?[a-z_]+>")


LIST_FIELDS = (
    "summary_points",
    "therapeutic_areas",
    "labelling_documents",
    "action_owners",
    "portfolio_impacts",
)


def _unwrap_json_strings(tool_input: dict, keys: tuple[str, ...] = LIST_FIELDS) -> dict:
    """Models occasionally return a list field as a JSON-encoded string. Decode those."""
    fixed = dict(tool_input)
    for key in keys:
        value = fixed.get(key)
        if isinstance(value, str):
            # Also drop stray XML-style tags the model sometimes appends, e.g. "[]</field>"
            cleaned = _STRAY_TAGS.sub("", value).strip()
            try:
                fixed[key] = json.loads(cleaned)
            except json.JSONDecodeError:
                pass  # leave it; validation will reject it with a clear message
    return fixed


def build_user_message(
    title: str, source: str, source_type: str, body_text: str
) -> str:
    body = body_text[:MAX_SOURCE_CHARS]
    return (
        f"Regulator: {source}\nDocument type: {source_type}\nTitle: {title}\n\n"
        f"<source_text>\n{body}\n</source_text>"
    )


def analyze_update(
    client,
    model: str,
    *,
    title: str,
    source: str,
    source_type: str,
    body_text: str,
    portfolio: list[dict],
) -> AnalysisResult:
    """Call Claude once and return a validated, citation-checked result."""
    names = [item["name"] for item in portfolio]
    response = call_with_tool(
        client,
        model=model,
        max_tokens=2500,
        system=build_system_prompt(portfolio),
        tool={
            "name": TOOL_NAME,
            "description": "Record the structured analysis of the regulatory update.",
            "input_schema": build_tool_schema(names),
        },
        messages=[
            {
                "role": "user",
                "content": build_user_message(title, source, source_type, body_text),
            }
        ],
    )

    tool_input = next(
        (block.input for block in response.content if block.type == "tool_use"), None
    )
    if tool_input is None:
        raise AnalysisError("Claude did not return a tool call")

    try:
        analysis = Analysis.model_validate(
            _unwrap_json_strings(tool_input), context={"portfolio": names}
        )
    except ValidationError as exc:
        raise AnalysisError(f"Output failed validation: {exc}") from exc

    points = verify_points([p.model_dump() for p in analysis.summary_points], body_text)
    return AnalysisResult(analysis=analysis, summary_points=points, model=model)
