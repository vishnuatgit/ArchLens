"""Quick script to analyze the ArchLens repo itself."""
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
            repo_type="library",
        )
        print("=" * 60)
        print("  ARCHLENS SELF-ANALYSIS REPORT")
        print("=" * 60)
        print(f"  Score    : {result['score']}/100")
        print(f"  Duration : {result['duration']}s")
        print(f"  Profile  : {result['repo_type']}")
        print()
        print("--- Dimension Breakdown ---")
        for dim, val in result["breakdown"].items():
            bar = "#" * val + "." * (20 - val)
            print(f"  {dim:20s} [{bar}] {val}/20")
        print()
        print("--- Strengths ---")
        for s in result["strengths"]:
            print(f"  [+] {s}")
        print()
        print("--- Weaknesses ---")
        for w in result["weaknesses"]:
            print(f"  [-] {w}")
        print()
        print("--- Suggestions ---")
        for i, s in enumerate(result["suggestions"], 1):
            print(f"  {i}. {s}")
        print("=" * 60)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(analyze())
