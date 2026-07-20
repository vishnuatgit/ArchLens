import asyncio
import logging
import sys
from pathlib import Path

# Add the root directory to the python path so 'app' can be imported
sys.path.append(str(Path(__file__).resolve().parent.parent))

from app.repositories.db import SessionLocal, Base, engine
from app.services.analysis_service import AnalysisService

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger("seed")

# A list of popular, public repositories to analyze for the seed data
SEED_REPOS = [
    "https://github.com/octocat/Hello-World",
    "https://github.com/fastapi/fastapi",
    "https://github.com/pallets/flask",
]


async def run_seed():
    logger.info("Starting ArchLens database seeding process...")

    # Ensure tables exist
    Base.metadata.create_all(bind=engine)

    db = SessionLocal()
    service = AnalysisService()

    success_count = 0
    try:
        for url in SEED_REPOS:
            logger.info(f"Analyzing repository: {url}")
            try:
                result = await service.run(db=db, url=url)
                logger.info(
                    f"Success! Analysis ID: {result['analysis_id']} | "
                    f"Score: {result['score']}/100"
                )
                success_count += 1
            except Exception as e:
                logger.error(f"Failed to analyze {url}: {e}")

            # Sleep briefly to avoid aggressive rate limiting, though the client also handles some
            await asyncio.sleep(2)

        logger.info(
            f"Seeding complete. Successfully analyzed {success_count}/{len(SEED_REPOS)} repositories."
        )
    finally:
        db.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_seed())
    except KeyboardInterrupt:
        logger.info("Seeding interrupted by user.")
