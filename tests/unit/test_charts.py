import math

from app.services.charts import (
    OTHER_LANGUAGE_COLOR,
    RADAR_CENTER,
    RADAR_RADIUS,
    language_color,
    radar_chart,
)
from app.services.metrics_service import DIMENSION_LABELS, DIMENSION_MAX_POINTS
from app.services.report_view import DimensionScore


def dimensions(fill: float) -> list[DimensionScore]:
    return [
        DimensionScore(
            key, label, round(DIMENSION_MAX_POINTS[key] * fill), DIMENSION_MAX_POINTS[key]
        )
        for key, label in DIMENSION_LABELS.items()
    ]


def test_full_marks_reach_the_end_of_every_axis():
    chart = radar_chart([("a/b", dimensions(1))])
    series = chart.series[0]
    assert len(chart.axes) == len(series.vertices) == 7
    for axis, vertex in zip(chart.axes, series.vertices, strict=True):
        assert math.isclose(vertex.x, axis.x, abs_tol=0.01)
        assert math.isclose(vertex.y, axis.y, abs_tol=0.01)
        assert math.isclose(math.dist((axis.x, axis.y), (120, 120)), RADAR_RADIUS, abs_tol=0.01)


def test_zero_points_sit_at_the_centre():
    vertices = radar_chart([("a/b", dimensions(0))]).series[0].vertices
    assert all((v.x, v.y) == (RADAR_CENTER, RADAR_CENTER) for v in vertices)


def test_first_axis_points_up_and_labels_extend_away_from_the_chart():
    chart = radar_chart([("a/b", dimensions(0.5))])
    first = chart.axes[0]
    assert first.key == "documentation"
    assert first.anchor == "top"
    assert math.isclose(first.x, RADAR_CENTER)
    anchors = [axis.anchor for axis in chart.axes]
    assert anchors[1:4] == ["start", "start", "start"]  # right-hand side
    assert anchors[4:] == ["end", "end", "end"]  # left-hand side
    assert all(0 <= axis.label_left <= 100 and 0 <= axis.label_top <= 100 for axis in chart.axes)


def test_two_series_share_the_axes():
    chart = radar_chart([("a/b", dimensions(1)), ("c/d", dimensions(0.4))])
    assert [s.name for s in chart.series] == ["a/b", "c/d"]
    assert len(chart.rings) == 4
    assert chart.series[1].vertices[0].points == round(15 * 0.4)


def test_language_colours_fall_back_to_grey():
    assert language_color("Python") == "#3572A5"
    assert language_color("Some new language") == OTHER_LANGUAGE_COLOR
