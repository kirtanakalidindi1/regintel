"""Request and response shapes for the API."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from regintel.llm.schema import (
    ActionOwner,
    ProductType,
    Relevance,
    SummaryPoint,
    TherapeuticArea,
    Topic,
)


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    model: str
    prompt_version: str
    created_at: datetime
    topic: str
    product_type: str
    therapeutic_areas: list[str]
    relevance: str
    relevance_rationale: str
    summary_points: list[dict]
    all_citations_supported: bool
    rare_disease: bool | None = None
    labelling_impact: bool | None = None
    labelling_documents: list[str] | None = None
    action_owners: list[str] | None = None
    portfolio_impacts: list[dict] | None = None
    review_status: str
    reviewed_output: dict | None
    reviewer_note: str | None
    reviewed_at: datetime | None


class UpdateSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_type: str
    title: str
    url: str
    published_date: date | None
    topic: str | None = None
    relevance: str | None = None
    therapeutic_areas: list[str] = []
    rare_disease: bool | None = None
    labelling_impact: bool | None = None
    action_owners: list[str] = []
    portfolio_items: list[str] = []
    review_status: str | None = None


class AssessmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    analysis_id: int
    model: str
    prompt_version: str
    created_at: datetime
    content: dict
    all_citations_supported: bool
    status: str
    reviewer_note: str | None
    reviewed_at: datetime | None


class AssessmentReviewIn(BaseModel):
    status: Literal["accepted", "needs_rework"]
    note: str | None = None


class UpdateDetail(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source: str
    source_type: str
    source_id: str
    title: str
    url: str
    published_date: date | None
    body_text: str
    analysis: AnalysisOut | None = None
    assessment: AssessmentOut | None = None


class UpdateList(BaseModel):
    total: int
    items: list[UpdateSummary]


class Corrections(BaseModel):
    """Reviewer's corrected labels. Only fields the reviewer changed need to be sent."""

    topic: Topic | None = None
    product_type: ProductType | None = None
    therapeutic_areas: list[TherapeuticArea] | None = Field(
        default=None, min_length=1, max_length=3
    )
    relevance: Relevance | None = None
    rare_disease: bool | None = None
    labelling_impact: bool | None = None
    action_owners: list[ActionOwner] | None = Field(
        default=None, min_length=1, max_length=4
    )
    summary_points: list[SummaryPoint] | None = Field(
        default=None, min_length=1, max_length=5
    )


class ReviewIn(BaseModel):
    status: Literal["approved", "corrected", "rejected"]
    corrections: Corrections | None = None
    note: str | None = None

    @model_validator(mode="after")
    def corrections_match_status(self):
        has_changes = self.corrections is not None and bool(
            self.corrections.model_dump(exclude_none=True)
        )
        if self.status == "corrected" and not has_changes:
            raise ValueError("status 'corrected' needs at least one correction")
        if self.status != "corrected" and has_changes:
            raise ValueError("corrections are only allowed with status 'corrected'")
        return self
