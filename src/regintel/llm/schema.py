"""The structured output we ask Claude for, and how we validate it."""

from typing import Literal

from pydantic import BaseModel, Field

from regintel.llm.taxonomy import PRODUCT_TYPES, RELEVANCE, THERAPEUTIC_AREAS, TOPICS

Topic = Literal[tuple(TOPICS)]  # type: ignore[valid-type]
ProductType = Literal[tuple(PRODUCT_TYPES)]  # type: ignore[valid-type]
TherapeuticArea = Literal[tuple(THERAPEUTIC_AREAS)]  # type: ignore[valid-type]
Relevance = Literal[tuple(RELEVANCE)]  # type: ignore[valid-type]


class SummaryPoint(BaseModel):
    claim: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class Analysis(BaseModel):
    topic: Topic
    product_type: ProductType
    therapeutic_areas: list[TherapeuticArea] = Field(min_length=1, max_length=3)
    relevance: Relevance
    relevance_rationale: str
    summary_points: list[SummaryPoint] = Field(min_length=1, max_length=5)


# JSON schema for the tool Claude must call. Written out by hand (no $refs) so it is
# easy to read and stays in step with the lists in taxonomy.py.
TOOL_NAME = "record_analysis"
TOOL_SCHEMA = {
    "type": "object",
    "properties": {
        "topic": {"type": "string", "enum": list(TOPICS)},
        "product_type": {"type": "string", "enum": list(PRODUCT_TYPES)},
        "therapeutic_areas": {
            "type": "array",
            "items": {"type": "string", "enum": THERAPEUTIC_AREAS},
            "minItems": 1,
            "maxItems": 3,
        },
        "relevance": {"type": "string", "enum": list(RELEVANCE)},
        "relevance_rationale": {
            "type": "string",
            "description": "One sentence explaining the relevance rating.",
        },
        "summary_points": {
            "type": "array",
            "minItems": 1,
            "maxItems": 5,
            "items": {
                "type": "object",
                "properties": {
                    "claim": {
                        "type": "string",
                        "description": "One plain-English sentence summarising a key fact.",
                    },
                    "quote": {
                        "type": "string",
                        "description": "A short passage copied character-for-character from "
                        "the source text that supports the claim.",
                    },
                },
                "required": ["claim", "quote"],
            },
        },
    },
    "required": [
        "topic",
        "product_type",
        "therapeutic_areas",
        "relevance",
        "relevance_rationale",
        "summary_points",
    ],
}
