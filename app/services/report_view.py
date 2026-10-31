"""
A display-ready view of one stored analysis.

The results page, the compare page and the Markdown export show the same facts,
so they all build them here instead of each decoding the JSON columns.
"""

import json
from dataclasses import dataclass
from datetime import datetime

from app.models.db_models import Analysis
from app.services.metrics_service import (
    API_PAGE_CAP,
    DIMENSION_LABELS,
    DIMENSION_MAX_POINTS,
    PROFILE_LABELS,
    RepoType,
    ScoreTier,
    format_capped_count,
    grade_for_score,
    score_tier,
)


@dataclass(frozen=True)
class DimensionScore:
    key: str
    label: str
    points: int
    max_points: int

    @property
    def percent(self) -> int:
        """Share of the available points, 0-100, used for bar widths."""
        if not self.max_points:
            return 0
        return max(0, min(100, round(self.points / self.max_points * 100)))


@dataclass(frozen=True)
class ReportView:
    id: int
    owner: str
    name: str
    url: str
    repo_type: str
    is_example: bool
    score: int
    grade: str
    summary: str
    created_at: datetime
    duration: float
    dimensions: list[DimensionScore]
    strengths: list[str]
    weaknesses: list[str]
    suggestions: list[str]
    languages: dict[str, float]
    stars: int
    forks: int
    open_issues: int
    contributor_count: int
    repo_size: int
    language_count: int
    last_pushed: datetime | None = None

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.name}"

    @property
    def tier(self) -> ScoreTier:
        return score_tier(self.score)

    @property
    def profile_label(self) -> str:
        try:
            return PROFILE_LABELS[RepoType(self.repo_type)]
        except ValueError:
            return self.repo_type.capitalize()

    @property
    def contributors_display(self) -> str:
        """Contributor counts come from one API page, so a full page is shown as '100+'."""
        return format_capped_count(self.contributor_count, API_PAGE_CAP)

    @property
    def days_since_push(self) -> int | None:
        """Days between the last push and the analysis, as the scorer measured them."""
        if self.last_pushed is None:
            return None
        return max(0, (self.created_at - self.last_pushed).days)

    @property
    def full_marks_count(self) -> int:
        return sum(1 for d in self.dimensions if d.points >= d.max_points)

    def dimension(self, key: str) -> DimensionScore:
        return next(d for d in self.dimensions if d.key == key)


def _json(raw: str | None, default):
    return json.loads(raw) if raw else default


def build_report_view(analysis: Analysis) -> ReportView:
    """Decodes a stored analysis (and its metrics row) into a ReportView."""
    m = analysis.metrics
    breakdown = _json(m.score_breakdown_json, {}) if m else {}
    dimensions = [
        DimensionScore(
            key=key,
            label=label,
            points=int(breakdown.get(key, 0)),
            max_points=DIMENSION_MAX_POINTS[key],
        )
        for key, label in DIMENSION_LABELS.items()
    ]
    return ReportView(
        id=analysis.id,
        owner=analysis.repository.owner,
        name=analysis.repository.name,
        url=analysis.repository.url,
        repo_type=analysis.repo_type,
        is_example=bool(analysis.is_example),
        score=analysis.score,
        grade=(m.health_grade if m else None) or grade_for_score(analysis.score),
        summary=(m.executive_summary if m else None) or "",
        created_at=analysis.created_at,
        duration=analysis.duration,
        dimensions=dimensions,
        strengths=_json(m.strengths_json, []) if m else [],
        weaknesses=_json(m.weaknesses_json, []) if m else [],
        suggestions=_json(m.suggestions_json, []) if m else [],
        languages=_json(m.languages_json, {}) if m else {},
        stars=m.stars if m else 0,
        forks=m.forks if m else 0,
        open_issues=m.open_issues if m else 0,
        contributor_count=m.contributor_count if m else 0,
        repo_size=m.repo_size if m else 0,
        language_count=m.language_count if m else 0,
        last_pushed=m.last_pushed if m else None,
    )


def describe_comparison(first: ReportView, second: ReportView) -> str:
    """One or two sentences summarising how two reports differ."""
    if first.score == second.score:
        sentence = f"{first.full_name} and {second.full_name} both score {first.score}/100."
    else:
        leader, other = (first, second) if first.score > second.score else (second, first)
        gap = leader.score - other.score
        points = "point" if gap == 1 else "points"
        sentence = (
            f"{leader.full_name} scores {gap} {points} higher ({leader.score} vs {other.score})."
        )

    # The dimension with the largest gap (the first one wins a tie), named with the
    # repository that leads it first, so the numbers never read the wrong way round
    pairs = list(zip(first.dimensions, second.dimensions, strict=True))
    left, right = max(pairs, key=lambda pair: abs(pair[0].points - pair[1].points))
    if left.points == right.points:
        return f"{sentence} Every dimension is tied."
    (ahead, ahead_dim), (behind, behind_dim) = sorted(
        ((first, left), (second, right)), key=lambda side: side[1].points, reverse=True
    )
    return (
        f"{sentence} The biggest difference is {left.label.lower()}: "
        f"{ahead_dim.points} for {ahead.full_name} vs {behind_dim.points} for "
        f"{behind.full_name}, out of {left.max_points}."
    )
