import json
from datetime import datetime

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db_models import Analysis
from app.services.metrics_service import RepoType
from app.services.seed_service import (
    EXAMPLES_PATH,
    export_example,
    load_examples,
    seed_examples_if_empty,
    seed_examples_on_startup,
)
from tests.db import fresh_engine


@pytest.fixture
def session_factory(tmp_path):
    engine = fresh_engine(f"sqlite:///{tmp_path / 'seed.db'}")
    yield sessionmaker(bind=engine)
    engine.dispose()


def test_bundled_examples_are_complete():
    examples = load_examples()
    assert len(examples) >= 2
    for example in examples:
        assert example["url"] == f"https://github.com/{example['owner']}/{example['name']}"
        assert example["repo_type"] in {t.value for t in RepoType}
        assert 0 <= example["score"] <= 100
        datetime.fromisoformat(example["analyzed_at"])
        metrics = example["metrics"]
        assert sum(metrics["score_breakdown"].values()) == example["score"]
        assert metrics["executive_summary"]


def test_seeds_empty_database_with_dated_example_reports(session_factory):
    db = session_factory()
    inserted = seed_examples_if_empty(db)

    examples = load_examples()
    analyses = db.query(Analysis).order_by(Analysis.id).all()
    assert inserted == len(examples) == len(analyses)
    assert all(a.is_example for a in analyses)
    # Seeded reports keep their real analysis date
    first = analyses[0]
    assert first.created_at == datetime.fromisoformat(examples[0]["analyzed_at"])
    # Round trip: exporting a seeded report reproduces the fixture entry
    assert export_example(first) == examples[0]
    db.close()


def test_does_not_seed_a_database_that_has_analyses(session_factory):
    db = session_factory()
    seed_examples_if_empty(db)
    assert seed_examples_if_empty(db) == 0
    assert db.query(Analysis).count() == len(load_examples())
    db.close()


def test_startup_seeding_survives_missing_tables(tmp_path, caplog):
    engine = create_engine(f"sqlite:///{tmp_path / 'empty.db'}")
    seed_examples_on_startup(sessionmaker(bind=engine))
    assert "Skipped loading example reports" in caplog.text
    engine.dispose()


def test_fixture_is_valid_json_with_lf_endings():
    raw = EXAMPLES_PATH.read_bytes()
    assert b"\r\n" not in raw
    assert "examples" in json.loads(raw)
