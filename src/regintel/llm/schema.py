"""The structured output we ask Claude for, and how we validate it."""

from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator, model_validator

from regintel.llm.taxonomy import (
    ACTION_OWNERS,
    LABELLING_DOCUMENTS,
    PRODUCT_TYPES,
    RELEVANCE,
    THERAPEUTIC_AREAS,
    TOPICS,
)

Topic = Literal[tuple(TOPICS)]  # type: ignore[valid-type]
ProductType = Literal[tuple(PRODUCT_TYPES)]  # type: ignore[valid-type]
TherapeuticArea = Literal[tuple(THERAPEUTIC_AREAS)]  # type: ignore[valid-type]
Relevance = Literal[tuple(RELEVANCE)]  # type: ignore[valid-type]
ActionOwner = Literal[tuple(ACTION_OWNERS)]  # type: ignore[valid-type]
LabellingDocument = Literal[tuple(LABELLING_DOCUMENTS)]  # type: ignore[valid-type]


class SummaryPoint(BaseModel):
    claim: str = Field(min_length=1)
    quote: str = Field(min_length=1)


class PortfolioImpact(BaseModel):
    watchlist_item: str
    reason: str = Field(min_length=1)

    @field_validator("watchlist_item")
    @classmethod
    def must_be_on_watchlist(cls, value: str, info: ValidationInfo) -> str:
        allowed = (info.context or {}).get("portfolio")
        if allowed is not None and value not in allowed:
            raise ValueError(f"{value!r} is not on the watchlist")
        return value


class Analysis(BaseModel):
    topic: Topic
    product_type: ProductType
    therapeutic_areas: list[TherapeuticArea] = Field(min_length=1, max_length=3)
    rare_disease: bool
    relevance: Relevance
    relevance_rationale: str
    labelling_impact: bool
    labelling_documents: list[LabellingDocument] = Field(
        default_factory=list, max_length=5
    )
    action_owners: list[ActionOwner] = Field(min_length=1, max_length=4)
    portfolio_impacts: list[PortfolioImpact] = Field(default_factory=list, max_length=5)
    summary_points: list[SummaryPoint] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def documents_match_impact(self):
        if not self.labelling_impact:
            self.labelling_documents = []
        return self


TOOL_NAME = "record_analysis"


def _enum_list(values, min_items=0, max_items=None, description=None) -> dict:
    schema = {
        "type": "array",
        "items": {"type": "string", "enum": list(values)},
        "minItems": min_items,
    }
    if max_items:
        schema["maxItems"] = max_items
    if description:
        schema["description"] = description
    return schema


def build_tool_schema(portfolio: list[str]) -> dict:
    """JSON schema for the tool Claude must call. Written out flat (no $refs)."""
    return {
        "type": "object",
        "properties": {
            "topic": {"type": "string", "enum": list(TOPICS)},
            "product_type": {"type": "string", "enum": list(PRODUCT_TYPES)},
            "therapeutic_areas": _enum_list(THERAPEUTIC_AREAS, 1, 3),
            "rare_disease": {
                "type": "boolean",
                "description": "True if the product treats a rare or orphan condition.",
            },
            "relevance": {"type": "string", "enum": list(RELEVANCE)},
            "relevance_rationale": {
                "type": "string",
                "description": "One sentence explaining the relevance rating.",
            },
            "labelling_impact": {
                "type": "boolean",
                "description": "True if the update requires or is likely to prompt changes to "
                "product information for the products concerned or their class.",
            },
            "labelling_documents": _enum_list(
                LABELLING_DOCUMENTS,
                0,
                5,
                "Which product information documents are affected. Empty if no impact.",
            ),
            "action_owners": _enum_list(ACTION_OWNERS, 1, 4),
            "portfolio_impacts": {
                "type": "array",
                "maxItems": 5,
                "description": "Watchlist items this update affects directly or as a class. "
                "Empty if none.",
                "items": {
                    "type": "object",
                    "properties": {
                        "watchlist_item": {"type": "string", "enum": portfolio},
                        "reason": {
                            "type": "string",
                            "description": "One sentence on why and what to check.",
                        },
                    },
                    "required": ["watchlist_item", "reason"],
                },
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
                            "description": "A short passage copied character-for-character "
                            "from the source text that supports the claim.",
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
            "rare_disease",
            "relevance",
            "relevance_rationale",
            "labelling_impact",
            "labelling_documents",
            "action_owners",
            "portfolio_impacts",
            "summary_points",
        ],
    }
