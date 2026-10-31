import re
import xml.etree.ElementTree as ET

import pytest

from app.models.db_models import Analysis, Metric
from app.services.badge_service import (
    LABEL_COLOR,
    NEUTRAL_COLOR,
    TIER_COLORS,
    badge_for_analysis,
    invalid_repository_badge,
    render_badge,
)


def _width(svg: str) -> int:
    return int(re.search(r'<svg[^>]* width="(\d+)"', svg).group(1))


def _luminance(hex_colour: str) -> float:
    channels = [int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast(first: str, second: str) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def test_badge_shows_grade_and_score_in_the_tier_colour():
    analysis = Analysis(score=77, metrics=Metric(health_grade="B+"))
    svg = badge_for_analysis(analysis)
    assert "B+ · 77/100" in svg
    assert TIER_COLORS["high"] in svg
    assert 'aria-label="ArchLens: B+ · 77/100"' in svg


@pytest.mark.parametrize(("score", "tier"), [(85, "high"), (55, "mid"), (12, "low")])
def test_badge_colour_follows_the_score_tier(score, tier):
    svg = badge_for_analysis(Analysis(score=score, metrics=Metric(health_grade="C")))
    assert TIER_COLORS[tier] in svg


def test_repository_without_a_stored_analysis_is_not_analyzed():
    svg = badge_for_analysis(None)
    assert "not analyzed" in svg
    assert NEUTRAL_COLOR in svg


def test_badges_are_well_formed_svg():
    for svg in (badge_for_analysis(None), invalid_repository_badge()):
        root = ET.fromstring(svg)
        assert root.tag == "{http://www.w3.org/2000/svg}svg"
        assert root.get("height") == "20"


def test_text_is_escaped():
    svg = render_badge("<script>", "a & b", "#000000")
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
    assert "a &amp; b" in svg
    ET.fromstring(svg)


def test_width_grows_with_the_message():
    assert _width(render_badge("ArchLens", "1234567890", "#000000")) > _width(
        render_badge("ArchLens", "1", "#000000")
    )


def test_white_badge_text_meets_wcag_aa_contrast():
    for colour in (LABEL_COLOR, NEUTRAL_COLOR, *TIER_COLORS.values()):
        assert _contrast(colour, "#ffffff") >= 4.5, colour
