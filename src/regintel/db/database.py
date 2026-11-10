"""Engine and session helpers."""

import logging

from sqlalchemy import Engine, create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from regintel.config import get_database_url
from regintel.db.models import Base

log = logging.getLogger(__name__)


def get_engine(url: str | None = None) -> Engine:
    return create_engine(url or get_database_url())


def init_db(engine: Engine) -> None:
    """Create missing tables, then add any new nullable columns to existing tables.

    A deliberately small stand-in for a migration tool: it only ever adds nullable
    columns, which is safe on both SQLite and Postgres.
    """
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            existing = {col["name"] for col in inspector.get_columns(table.name)}
            for column in table.columns:
                if column.name in existing:
                    continue
                if not column.nullable:
                    raise RuntimeError(
                        f"Cannot add non-nullable column {table.name}.{column.name} automatically"
                    )
                col_type = column.type.compile(dialect=engine.dialect)
                conn.execute(
                    text(
                        f'ALTER TABLE {table.name} ADD COLUMN "{column.name}" {col_type}'
                    )
                )
                log.info("Added column %s.%s", table.name, column.name)


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
