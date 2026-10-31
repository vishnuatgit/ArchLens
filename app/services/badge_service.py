"""
Shields-style SVG badges for README files.

A README badge is downloaded every time someone views that README, so the badge
endpoint must never call GitHub: it only reads analyses already stored in the
database. Scores refresh when someone runs a new analysis.
"""

from xml.sax.saxutils import escape

from app.models.db_models import Analysis
from app.services.metrics_service import grade_for_score, score_tier

LABEL = "ArchLens"
LABEL_COLOR = "#33383e"
NEUTRAL_COLOR = "#5f656c"
# Dark enough for white text to pass WCAG AA (4.5:1) on every badge
TIER_COLORS = {"high": "#2a6a3e", "mid": "#875700", "low": "#a3352b"}

HEIGHT = 20
PADDING = 6  # horizontal space on each side of a text
# Verdana at 11px averages about 6.8px per character. The SVG sets textLength,
# so renderers fit the text to exactly this width whatever font they have.
CHAR_WIDTH = 6.8


def _text_width(text: str) -> int:
    return round(len(text) * CHAR_WIDTH)


def render_badge(label: str, message: str, color: str) -> str:
    """Returns a flat two-part badge: a grey label on the left, a coloured message on the right."""
    label_text, message_text = _text_width(label), _text_width(message)
    label_box = label_text + 2 * PADDING
    message_box = message_text + 2 * PADDING
    width = label_box + message_box
    title = escape(f"{label}: {message}")
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{HEIGHT}" '
        f'role="img" aria-label="{title}">'
        f"<title>{title}</title>"
        f'<g shape-rendering="crispEdges">'
        f'<rect width="{label_box}" height="{HEIGHT}" fill="{LABEL_COLOR}"/>'
        f'<rect x="{label_box}" width="{message_box}" height="{HEIGHT}" fill="{color}"/>'
        f"</g>"
        f'<g fill="#fff" text-anchor="middle" '
        f'font-family="Verdana,Geneva,DejaVu Sans,sans-serif" font-size="11">'
        f'<text x="{label_box / 2:g}" y="14" textLength="{label_text}">{escape(label)}</text>'
        f'<text x="{label_box + message_box / 2:g}" y="14" textLength="{message_text}">'
        f"{escape(message)}</text>"
        f"</g></svg>"
    )


def badge_for_analysis(analysis: Analysis | None) -> str:
    """The badge for a repository's latest stored analysis, or a neutral 'not analyzed' one."""
    if analysis is None:
        return render_badge(LABEL, "not analyzed", NEUTRAL_COLOR)
    grade = (analysis.metrics.health_grade if analysis.metrics else None) or grade_for_score(
        analysis.score
    )
    color = TIER_COLORS[score_tier(analysis.score).key]
    return render_badge(LABEL, f"{grade} · {analysis.score}/100", color)


def invalid_repository_badge() -> str:
    return render_badge(LABEL, "invalid repository", NEUTRAL_COLOR)
