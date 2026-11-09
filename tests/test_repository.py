import pytest

from regintel.db.database import get_engine, get_sessionmaker, init_db
from regintel.db.models import Update
from regintel.db.repository import upsert_updates
from regintel.ingest import fda
from tests.test_fda import SAMPLE


@pytest.fixture
def session():
    engine = get_engine("sqlite://")  # in-memory database, fresh for each test
    init_db(engine)
    with get_sessionmaker(engine)() as s:
        yield s


def rec(**overrides):
    return fda.normalize_enforcement({**SAMPLE, **overrides}, "drug_enforcement")


def test_insert_then_rerun_is_unchanged(session):
    assert upsert_updates(session, [rec()])["inserted"] == 1
    assert upsert_updates(session, [rec()])["unchanged"] == 1
    assert session.query(Update).count() == 1


def test_changed_record_is_updated_not_duplicated(session):
    upsert_updates(session, [rec()])
    counts = upsert_updates(session, [rec(status="Terminated")])
    assert counts["updated"] == 1
    stored = session.query(Update).one()
    assert "Status: Terminated" in stored.body_text


def test_duplicates_within_a_batch_are_skipped(session):
    counts = upsert_updates(session, [rec(), rec()])
    assert counts == {
        "inserted": 1,
        "updated": 0,
        "unchanged": 0,
        "duplicates_in_batch": 1,
    }


def test_different_recalls_are_both_stored(session):
    upsert_updates(session, [rec(), rec(recall_number="D-0456-2026")])
    assert session.query(Update).count() == 2
