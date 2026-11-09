"""Engine and session helpers."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from regintel.config import get_database_url
from regintel.db.models import Base


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_database_url())


def init_db(engine: Engine) -> None:
    """Create any tables that don't exist yet."""
    Base.metadata.create_all(engine)


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
