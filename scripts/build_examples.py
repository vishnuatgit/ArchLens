"""
Regenerates app/seed/examples.json, the example reports loaded into an empty database.

Runs live analyses (about six GitHub API calls each, so it works without a token)
against a throwaway SQLite database and exports the stored results.

Usage:
    python scripts/build_examples.py
"""

import asyncio
import json
import sys
import tempfile
from pathlib import Path

# Add the root directory to the python path so 'app' can be imported
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.db_models import Analysis
from app.repositories.db import Base
from app.services.analysis_service import AnalysisService
from app.services.seed_service import EXAMPLES_PATH, export_example

# (repository, profile) pairs shown as examples, in display order
EXAMPLE_REPOS = [
    ("psf/requests", "library"),
    ("pallets/flask", "library"),
    ("vishnuatgit/ArchLens", "library"),
]


async def build_examples() -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'examples.db'}")
        Base.metadata.create_all(bind=engine)
        db = sessionmaker(bind=engine)()
        service = AnalysisService()
        examples = []
        try:
            for repo, profile in EXAMPLE_REPOS:
                result = await service.run(db=db, url=repo, repo_type=profile)
                print(f"{repo}: {result['score']}/100 in {result['duration']}s")
                examples.append(export_example(db.get(Analysis, result["analysis_id"])))
        finally:
            db.close()
            await service.github.aclose()
            engine.dispose()
    return examples


def main() -> None:
    examples = asyncio.run(build_examples())
    payload = {
        "description": (
            "Real ArchLens analyses captured by scripts/build_examples.py. They are loaded "
            "into an empty database on startup and labelled as examples in the UI."
        ),
        "examples": examples,
    }
    with EXAMPLES_PATH.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
        f.write("\n")
    print(f"Wrote {len(examples)} examples to {EXAMPLES_PATH}")


if __name__ == "__main__":
    main()
