"""
Geometry and colours for the charts on the report and compare pages.

Charts are inline SVG rendered by the templates, so the shapes are computed here
and the templates only draw them. Labels are HTML positioned in percentages, so
they stay readable when the SVG scales down on a phone.
"""

import math
from dataclasses import dataclass

from app.services.report_view import DimensionScore

# Radar layout in SVG user units. The view box leaves room around the chart
# for the HTML labels that sit outside it.
RADAR_CENTER = 120.0
RADAR_RADIUS = 100.0
RADAR_LABEL_GAP = 16.0
RADAR_VIEW_BOX = (-100.0, -34.0, 440.0, 308.0)  # x, y, width, height
RADAR_RINGS = (25, 50, 75, 100)


@dataclass(frozen=True)
class RadarAxis:
    key: str
    label: str
    x: float  # end of the axis line (100%)
    y: float
    label_left: float  # label anchor, as a percentage of the chart box
    label_top: float
    anchor: str  # "start", "end", "top" or "bottom": which way the label extends


@dataclass(frozen=True)
class RadarVertex:
    x: float
    y: float
    label: str
    points: int
    max_points: int


@dataclass(frozen=True)
class RadarSeries:
    name: str
    polygon: str  # "x,y x,y ..." for <polygon points>
    vertices: tuple[RadarVertex, ...]


@dataclass(frozen=True)
class RadarChart:
    view_box: str
    aspect: str  # CSS aspect-ratio of the chart box
    axes: tuple[RadarAxis, ...]
    rings: tuple[str, ...]  # polygons for the 25/50/75/100% grid
    series: tuple[RadarSeries, ...]


def _point(index: int, count: int, fraction: float) -> tuple[float, float]:
    """A point on axis `index` (0 points straight up, then clockwise) at `fraction` of the radius."""
    angle = -math.pi / 2 + 2 * math.pi * index / count
    radius = RADAR_RADIUS * fraction
    return (
        round(RADAR_CENTER + radius * math.cos(angle), 2),
        round(RADAR_CENTER + radius * math.sin(angle), 2),
    )


def _polygon(points: list[tuple[float, float]]) -> str:
    return " ".join(f"{x:g},{y:g}" for x, y in points)


def _anchor(x: float, y: float) -> str:
    dx, dy = x - RADAR_CENTER, y - RADAR_CENTER
    if abs(dx) < 1:
        return "top" if dy < 0 else "bottom"
    return "start" if dx > 0 else "end"


def radar_chart(series: list[tuple[str, list[DimensionScore]]]) -> RadarChart:
    """
    A radar chart of one or more reports' dimension scores, each axis showing
    the share of that dimension's points (0-100%). All series share the axes
    of the first one.
    """
    dimensions = series[0][1]
    count = len(dimensions)
    vx, vy, vw, vh = RADAR_VIEW_BOX

    axes = []
    for index, dim in enumerate(dimensions):
        x, y = _point(index, count, 1)
        lx, ly = _point(index, count, 1 + RADAR_LABEL_GAP / RADAR_RADIUS)
        axes.append(
            RadarAxis(
                key=dim.key,
                label=dim.label,
                x=x,
                y=y,
                label_left=round((lx - vx) / vw * 100, 2),
                label_top=round((ly - vy) / vh * 100, 2),
                anchor=_anchor(x, y),
            )
        )

    rings = tuple(
        _polygon([_point(i, count, ring / 100) for i in range(count)]) for ring in RADAR_RINGS
    )

    drawn = []
    for name, dims in series:
        vertices = tuple(
            RadarVertex(
                *_point(index, count, dim.percent / 100),
                label=dim.label,
                points=dim.points,
                max_points=dim.max_points,
            )
            for index, dim in enumerate(dims)
        )
        drawn.append(
            RadarSeries(
                name=name,
                polygon=_polygon([(v.x, v.y) for v in vertices]),
                vertices=vertices,
            )
        )

    return RadarChart(
        view_box=" ".join(f"{value:g}" for value in RADAR_VIEW_BOX),
        aspect=f"{vw:g} / {vh:g}",
        axes=tuple(axes),
        rings=rings,
        series=tuple(drawn),
    )


# Colours GitHub uses for common languages (from its open-source linguist data),
# so the language bar looks the way developers expect. Other languages fall back
# to a neutral grey; the legend always names every language, so colour is never
# the only cue.
LANGUAGE_COLORS = {
    "Assembly": "#6E4C13",
    "Astro": "#ff5a03",
    "Batchfile": "#C1F12E",
    "C": "#555555",
    "C#": "#178600",
    "C++": "#f34b7d",
    "CMake": "#DA3434",
    "CSS": "#663399",
    "Clojure": "#db5855",
    "CoffeeScript": "#244776",
    "Cython": "#fedf5b",
    "Dart": "#00B4AB",
    "Dockerfile": "#384d54",
    "Elixir": "#6e4a7e",
    "Elm": "#60B5CC",
    "Erlang": "#B83998",
    "Go": "#00ADD8",
    "Groovy": "#4298b8",
    "HCL": "#844FBA",
    "HTML": "#e34c26",
    "Haskell": "#5e5086",
    "Java": "#b07219",
    "JavaScript": "#f1e05a",
    "Jinja": "#a52a22",
    "Julia": "#a270ba",
    "Jupyter Notebook": "#DA5B0B",
    "Kotlin": "#A97BFF",
    "Less": "#1d365d",
    "Lua": "#000080",
    "MDX": "#fcb32c",
    "Makefile": "#427819",
    "Mako": "#7e858d",
    "Nix": "#7e7eff",
    "OCaml": "#ef7a08",
    "Objective-C": "#438eff",
    "PHP": "#4F5D95",
    "Perl": "#0298c3",
    "PowerShell": "#012456",
    "Python": "#3572A5",
    "R": "#198CE7",
    "Roff": "#ecdebe",
    "Ruby": "#701516",
    "Rust": "#dea584",
    "SCSS": "#c6538c",
    "Scala": "#c22d40",
    "Shell": "#89e051",
    "Solidity": "#AA6746",
    "Svelte": "#ff3e00",
    "Swift": "#F05138",
    "TeX": "#3D6117",
    "TypeScript": "#3178c6",
    "Vue": "#41b883",
    "Zig": "#ec915c",
}
OTHER_LANGUAGE_COLOR = "#8b949e"


def language_color(language: str) -> str:
    return LANGUAGE_COLORS.get(language, OTHER_LANGUAGE_COLOR)
