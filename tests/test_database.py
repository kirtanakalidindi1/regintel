from sqlalchemy import create_engine, inspect, text

from regintel.db.database import init_db
from regintel.db.models import Base

V3_COLUMNS = [
    "rare_disease",
    "labelling_impact",
    "labelling_documents",
    "action_owners",
    "portfolio_impacts",
]


def test_init_db_adds_new_columns_to_an_existing_database(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    # Recreate the database as it looked before prompt v3: same tables, without v3 columns
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for col in V3_COLUMNS:
            conn.execute(text(f"ALTER TABLE analyses DROP COLUMN {col}"))
    assert "labelling_impact" not in {
        c["name"] for c in inspect(engine).get_columns("analyses")
    }

    init_db(engine)

    columns = {c["name"] for c in inspect(engine).get_columns("analyses")}
    assert set(V3_COLUMNS) <= columns


def test_init_db_is_idempotent(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'db.db'}")
    init_db(engine)
    init_db(engine)  # second run must not try to add columns again
