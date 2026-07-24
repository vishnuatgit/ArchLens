"""Quick script to analyze ArchLens under personal profile."""
import asyncio
from app.repositories.db import SessionLocal, Base, engine
from app.services.analysis_service import AnalysisService


async def analyze():
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    service = AnalysisService()
    try:
        result = await service.run(
            db=db,
            url="https://github.com/vishnuatgit/ArchLens.git",
            repo_type="personal",
        )
        print("=" * 60)
        print("  ARCHLENS SELF-ANALYSIS (PERSONAL PROFILE)")
        print("=" * 60)
        print(f"  Score    : {result['score']}/100")
        print(f"  Profile  : {result['repo_type']}")
        print()
        print("--- Dimension Breakdown ---")
        for dim, val in result["breakdown"].items():
            bar = "#" * val + "." * (20 - val)
            print(f"  {dim:20s} [{bar}] {val}/20")
        print()
        print("--- Weaknesses ---")
        for w in result["weaknesses"]:
            print(f"  [-] {w}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(analyze())
