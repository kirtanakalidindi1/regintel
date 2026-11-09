"""Ask Claude for a structured, source-grounded analysis of one regulatory update."""

from dataclasses import dataclass

from pydantic import ValidationError

from regintel.llm.citations import verify_points
from regintel.llm.schema import TOOL_NAME, TOOL_SCHEMA, Analysis
from regintel.llm.taxonomy import (
    PRODUCT_TYPES,
    RELEVANCE,
    THERAPEUTIC_AREAS,
    TOPICS,
    describe,
)

PROMPT_VERSION = "v1"
MAX_SOURCE_CHARS = 30_000

SYSTEM_PROMPT = f"""You are a regulatory intelligence analyst. You read one official FDA or \
MHRA update and record a structured analysis by calling the {TOOL_NAME} tool.

Rules:
- Use only the source text you are given. Do not add facts from outside knowledge.
- Every summary point needs a quote copied exactly, character for character, from the source \
text. Keep quotes short (one sentence or less) and do not paraphrase inside a quote.
- Write 2 to 5 summary points covering: what product is affected, what the issue is, and what \
action is required and by whom.
- Choose labels only from the lists below.

Topics:
{describe(TOPICS)}

Product types:
{describe(PRODUCT_TYPES)}

Therapeutic areas (pick 1 to 3): {", ".join(THERAPEUTIC_AREAS)}

Relevance:
{describe(RELEVANCE)}"""


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


def build_user_message(
    title: str, source: str, source_type: str, body_text: str
) -> str:
    body = body_text[:MAX_SOURCE_CHARS]
    return (
        f"Regulator: {source}\nDocument type: {source_type}\nTitle: {title}\n\n"
        f"<source_text>\n{body}\n</source_text>"
    )


def analyze_update(
    client, model: str, *, title: str, source: str, source_type: str, body_text: str
) -> AnalysisResult:
    """Call Claude once and return a validated, citation-checked result."""
    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=SYSTEM_PROMPT,
        tools=[
            {
                "name": TOOL_NAME,
                "description": "Record the structured analysis of the regulatory update.",
                "input_schema": TOOL_SCHEMA,
            }
        ],
        tool_choice={"type": "tool", "name": TOOL_NAME},
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
        analysis = Analysis.model_validate(tool_input)
    except ValidationError as exc:
        raise AnalysisError(f"Output failed validation: {exc}") from exc

    points = verify_points([p.model_dump() for p in analysis.summary_points], body_text)
    return AnalysisResult(analysis=analysis, summary_points=points, model=model)
