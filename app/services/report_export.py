"""
Exports a report as Markdown, for pasting into an issue, a pull request or notes.
"""

from app.config import SITE
from app.formatting import format_size_kb
from app.services.dependency_service import SCORE_NOTE, DependencyScan
from app.services.evidence import build_evidence, build_fix_plan
from app.services.report_view import ReportView


def _fix_lines(report: ReportView) -> list[str]:
    """The same "what to fix first" list as the report page, with the points each fix adds."""
    plan = build_fix_plan(report, build_evidence(report))
    if plan is None:
        return [f"{number}. {item}" for number, item in enumerate(report.suggestions, 1)]
    lines = [
        f"{number}. {fix.action} ({'' if fix.exact else 'up to '}+{fix.gain} points, "
        f"{fix.dimension_label.lower()})"
        for number, fix in enumerate(plan.fixes, 1)
    ]
    if plan.exact_gain:
        lines += [
            "",
            f"The file-level fixes add {plan.exact_gain} points: {report.score} → "
            f"{plan.projected_score} ({plan.projected_grade}).",
        ]
    return lines


def _dependency_lines(scan: DependencyScan | None) -> list[str]:
    """The "Dependencies" and "Known vulnerabilities" sections, with the same wording as the page."""
    if scan is None:
        return [
            "## Dependencies",
            "",
            "Not scanned: this report was stored before dependency scanning existed.",
            "",
        ]
    lines = ["## Dependencies", "", scan.summary_line, ""]
    for ecosystem, members in scan.by_ecosystem():
        lines += [
            f"**{ecosystem}**",
            "",
            "| Package | Declared | Version | Status |",
            "| :-- | :-- | :-- | :-- |",
        ]
        for d in members:
            status = "pinned" if d.pinned else "not pinned"
            name = f"{d.name} (dev)" if d.dev else d.name
            lines.append(f"| {name} | `{d.spec or 'any'}` | {d.version or '-'} | {status} |")
        lines.append("")
    lines += [f"_{note}_" for note in scan.notes]
    lines += ["## Known vulnerabilities", ""]
    if scan.vulnerability_check == "ok" and scan.vulnerabilities:
        lines += ["| Severity | Package | Advisory | Fix |", "| :-- | :-- | :-- | :-- |"]
        lines += [
            f"| {v.severity} | {v.package} {v.version} | [{v.id}]({v.url}) | "
            f"{'upgrade to ' + v.fixed if v.fixed else 'no fixed version listed'} |"
            for v in scan.vulnerabilities
        ]
    elif scan.vulnerability_check == "ok":
        lines.append(f"None found in {scan.checked} checked pinned dependencies (OSV.dev).")
    elif scan.vulnerability_check == "unavailable":
        lines.append("Could not check: OSV.dev did not answer. Analyze again later.")
    else:
        lines.append("Not checked: no dependency has an exact version.")
    lines += ["", f"_{SCORE_NOTE}_", ""]
    return lines


def report_to_markdown(report: ReportView, report_url: str | None = None) -> str:
    """Renders a report as a self-contained Markdown document."""
    analyzed = report.created_at.strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        f"# ArchLens report: {report.full_name}",
        "",
        f"**Score:** {report.score}/100 · **Grade:** {report.grade} · "
        f"**Tier:** {report.tier.label}  ",
        f"**Profile:** {report.profile_label} · **Analyzed:** {analyzed}  ",
        f"**Repository:** {report.url}",
        "",
    ]

    if report.is_example:
        lines += [
            f"> Example report, captured from live GitHub data on "
            f"{report.created_at:%Y-%m-%d}. The numbers reflect that date.",
            "",
        ]

    if report.summary:
        lines += [report.summary, ""]

    lines += [
        "## Dimension scores",
        "",
        "| Dimension | Points | Out of |",
        "| :-- | --: | --: |",
    ]
    lines += [f"| {d.label} | {d.points} | {d.max_points} |" for d in report.dimensions]
    lines += [f"| **Total** | **{report.score}** | **100** |", ""]

    fix_lines = _fix_lines(report)
    if fix_lines:
        lines += ["## What to fix first", "", *fix_lines, ""]

    if report.weaknesses:
        lines += ["## Concerns", ""]
        lines += [f"- {item}" for item in report.weaknesses]
        lines.append("")

    if report.strengths:
        lines += ["## Strengths", ""]
        lines += [f"- {item}" for item in report.strengths]
        lines.append("")

    lines += _dependency_lines(report.dependency_scan)

    lines += [
        "## Repository facts",
        "",
        "| Stars | Forks | Open issues | Contributors | Size | Languages |",
        "| --: | --: | --: | --: | --: | --: |",
        f"| {report.stars:,} | {report.forks:,} | {report.open_issues:,} | "
        f"{report.contributors_display} | {format_size_kb(report.repo_size)} | "
        f"{report.language_count} |",
        "",
    ]
    if report.languages:
        languages = ", ".join(f"{lang} {pct}%" for lang, pct in report.languages.items())
        lines += [f"Languages: {languages}", ""]

    footer = f"Generated by [ArchLens]({SITE['repo_url']}) from public GitHub metadata."
    if report_url:
        footer += f" Full report: {report_url}"
    lines += ["---", "", footer, ""]
    return "\n".join(lines)


def markdown_filename(report: ReportView) -> str:
    """A download name such as 'archlens-psf-requests-2026-10-31.md'."""
    return f"archlens-{report.owner}-{report.name}-{report.created_at:%Y-%m-%d}.md".lower()


# Hidden marker that lets the GitHub Action find its own pull-request comment and update it
COMMENT_MARKER = "<!-- archlens-health-comment -->"
COMMENT_FIX_LIMIT = 3


def _top_fixes(report: ReportView, limit: int = COMMENT_FIX_LIMIT):
    plan = build_fix_plan(report, build_evidence(report))
    return list(plan.fixes[:limit]) if plan else []


def report_to_comment(report: ReportView, report_url: str | None = None) -> str:
    """A short Markdown comment for a pull request: score, grade, top fixes, dependencies."""
    lines = [
        COMMENT_MARKER,
        f"### ArchLens health: {report.score}/100 ({report.grade})",
        "",
        f"**{report.full_name}** is rated *{report.tier.label}* under the "
        f"{report.profile_label.lower()} profile.",
        "",
    ]
    fixes = _top_fixes(report)
    if fixes:
        lines += ["**Top fixes**", ""]
        lines += [
            f"{number}. {fix.action} ({'' if fix.exact else 'up to '}+{fix.gain} points)"
            for number, fix in enumerate(fixes, 1)
        ]
        lines.append("")
    if report.dependency_scan is not None:
        lines += [f"**Dependencies:** {report.dependency_scan.summary_line}", ""]
    footer = f"Updated by [ArchLens]({SITE['repo_url']})"
    if report_url:
        footer += f" · [full report]({report_url})"
    lines += [f"<sub>{footer}</sub>", ""]
    return "\n".join(lines)


def report_to_summary(report: ReportView) -> dict:
    """The machine-readable summary printed by `archlens analyze --format json`."""
    scan = report.dependency_scan
    checked = scan is not None and scan.vulnerability_check == "ok"
    return {
        "repository": report.full_name,
        "url": report.url,
        "profile": report.repo_type,
        "score": report.score,
        "grade": report.grade,
        "tier": report.tier.label,
        "analyzed_at": report.created_at.isoformat(timespec="seconds"),
        "dimensions": {d.key: {"points": d.points, "max": d.max_points} for d in report.dimensions},
        "top_fixes": [
            {
                "action": fix.action,
                "gain": fix.gain,
                "exact": fix.exact,
                "dimension": fix.dimension_label,
            }
            for fix in _top_fixes(report, limit=10)
        ],
        "dependencies": (
            None
            if scan is None
            else {
                "status": scan.status,
                "total": len(scan.dependencies),
                "pinned": scan.pinned_count,
                "vulnerability_check": scan.vulnerability_check,
                "vulnerabilities": scan.to_dict()["vulnerabilities"] if checked else [],
            }
        ),
        # None when nothing could be checked, so a gate never mistakes "unknown" for "zero"
        "vulnerability_count": len(scan.vulnerabilities) if checked else None,
    }
