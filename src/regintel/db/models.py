"""Database tables. SQLAlchemy keeps these portable between SQLite and Postgres."""

from datetime import UTC, date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Update(Base):
    """One regulatory update (a recall, safety alert, guidance notice, ...)."""

    __tablename__ = "updates"
    __table_args__ = (
        UniqueConstraint(
            "source", "source_type", "source_id", name="uq_update_identity"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), index=True)
    source_type: Mapped[str] = mapped_column(String(50), index=True)
    source_id: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(500))
    url: Mapped[str] = mapped_column(String(1000))
    published_date: Mapped[date | None] = mapped_column(Date, index=True)
    body_text: Mapped[str] = mapped_column(Text)
    raw: Mapped[dict] = mapped_column(JSON)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    analyses: Mapped[list["AnalysisRecord"]] = relationship(back_populates="update")


class AnalysisRecord(Base):
    """One AI analysis of an update, plus its human review status."""

    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True)
    update_id: Mapped[int] = mapped_column(ForeignKey("updates.id"), index=True)
    model: Mapped[str] = mapped_column(String(100))
    prompt_version: Mapped[str] = mapped_column(String(20), index=True)
    source_hash: Mapped[str] = mapped_column(
        String(64)
    )  # update content this was based on
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    topic: Mapped[str] = mapped_column(String(50), index=True)
    product_type: Mapped[str] = mapped_column(String(50), index=True)
    therapeutic_areas: Mapped[list] = mapped_column(JSON)
    relevance: Mapped[str] = mapped_column(String(10), index=True)
    relevance_rationale: Mapped[str] = mapped_column(Text)
    summary_points: Mapped[list] = mapped_column(JSON)  # [{claim, quote, supported}]
    all_citations_supported: Mapped[bool] = mapped_column(Boolean)

    # Human-in-the-loop review, filled in from the review screen later
    review_status: Mapped[str] = mapped_column(
        String(20), default="pending", index=True
    )
    reviewed_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    update: Mapped[Update] = relationship(back_populates="analyses")
