"""
README badge endpoint.

Reads stored analyses only and never calls GitHub, so a badge embedded in a
popular README cannot use up the server's GitHub API quota.
"""

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.dependencies import get_repository_service
from app.repositories.db import get_db
from app.services.badge_service import badge_for_analysis, invalid_repository_badge
from app.services.github_service import canonical_github_url, parse_github_url
from app.services.metrics_service import RepoType
from app.services.repository_service import RepositoryService

router = APIRouter(tags=["Badges"])

SVG_MEDIA_TYPE = "image/svg+xml; charset=utf-8"
# A stored score only changes when someone re-runs the analysis, so an hour of
# caching is safe; a missing badge is cached briefly so it appears soon after a first run.
CACHE_ANALYZED = "public, max-age=3600"
CACHE_NOT_ANALYZED = "public, max-age=300"


@router.get(
    "/badge/{owner}/{repo}.svg",
    response_class=Response,
    summary="README badge",
    description=(
        "An SVG badge with the grade and score of the repository's latest stored analysis, "
        "or 'not analyzed'. Never calls GitHub."
    ),
    responses={200: {"content": {"image/svg+xml": {}}}, 400: {"content": {"image/svg+xml": {}}}},
)
def repo_badge(
    owner: str,
    repo: str,
    profile: RepoType | None = None,
    db: Session = Depends(get_db),
    repo_svc: RepositoryService = Depends(get_repository_service),
):
    parsed_owner, parsed_name = parse_github_url(f"{owner}/{repo}")
    if not parsed_owner or not parsed_name:
        return Response(
            invalid_repository_badge(),
            status_code=400,
            media_type=SVG_MEDIA_TYPE,
            headers={"Cache-Control": CACHE_NOT_ANALYZED},
        )

    analysis = repo_svc.get_latest_analysis(
        db, canonical_github_url(parsed_owner, parsed_name), profile.value if profile else None
    )
    return Response(
        badge_for_analysis(analysis),
        media_type=SVG_MEDIA_TYPE,
        headers={"Cache-Control": CACHE_ANALYZED if analysis else CACHE_NOT_ANALYZED},
    )
