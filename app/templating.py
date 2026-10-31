"""
Shared Jinja2 environment for the web pages.

Registers the formatting filters and scoring helpers used by the templates so
that the web router and the application-level error handlers render identically.
"""

from pathlib import Path

from fastapi.templating import Jinja2Templates

from app.config import SITE
from app.formatting import compact_number, format_size_kb
from app.services.metrics_service import (
    API_PAGE_CAP,
    DIMENSION_LABELS,
    DIMENSION_MAX_POINTS,
    PROFILE_LABELS,
    grade_for_score,
    score_tier,
)

TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# Bump when CSS or JS changes so browsers fetch the new files
ASSET_VERSION = "3.1"

# compact_number and format_size_kb stay importable from here for existing callers
__all__ = ["compact_number", "format_size_kb", "templates"]

templates = Jinja2Templates(directory=TEMPLATES_DIR)
templates.env.filters["compact"] = compact_number
templates.env.filters["size_kb"] = format_size_kb
templates.env.globals["score_tier"] = score_tier
# Rows stored without a grade show the grade their score maps to, never a made-up one
templates.env.globals["grade_for"] = grade_for_score
templates.env.globals["max_points"] = DIMENSION_MAX_POINTS
templates.env.globals["dimension_labels"] = DIMENSION_LABELS
templates.env.globals["profiles"] = {str(key): label for key, label in PROFILE_LABELS.items()}
templates.env.globals["api_page_cap"] = API_PAGE_CAP
templates.env.globals["site"] = SITE
templates.env.globals["asset_version"] = ASSET_VERSION
