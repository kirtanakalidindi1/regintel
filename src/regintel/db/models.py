"""Database tables. SQLAlchemy keeps these portable between SQLite and Postgres."""

from datetime import UTC, date, datetime

from sqlalchemy import JSON, Date, DateTime, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


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
