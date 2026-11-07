import asyncio
import json
import sys
from contextlib import nullcontext
from enum import StrEnum
from pathlib import Path

# Force UTF-8 encoding for Windows console (fixes UnicodeEncodeError for checkmarks)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.exceptions import (
    ArchLensError,
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)
from app.models.db_models import Analysis
from app.repositories.db import SessionLocal
from app.services.analysis_service import AnalysisService
from app.services.dependency_service import SCORE_NOTE, DependencyScan
from app.services.metrics_service import DIMENSION_MAX_POINTS, score_tier
from app.services.report_export import report_to_comment, report_to_markdown, report_to_summary
from app.services.report_view import ReportView, build_report_view

app = typer.Typer(help="ArchLens CLI - engineering health scoring for GitHub repositories")
console = Console()
# Messages that must not mix with a Markdown or JSON report printed on stdout
err_console = Console(stderr=True)

# Exit codes: 0 success, 1 the analysis failed, 2 the score is below --min-score
EXIT_ERROR = 1
EXIT_BELOW_MIN_SCORE = 2


class OutputFormat(StrEnum):
    RICH = "rich"
    MARKDOWN = "markdown"
    JSON = "json"


@app.callback()
def main() -> None:
    """
    ArchLens: engineering health scores for public GitHub repositories.

    A callback keeps `analyze` a named subcommand (`archlens analyze owner/repo`);
    without one, Typer folds a single-command app into the command itself.
    """


async def async_analyze(url: str, profile: str) -> dict:
    """Async wrapper to run the AnalysisService."""
    service = AnalysisService()
    # Provide the database session
    db = SessionLocal()
    try:
        # Run the full pipeline
        result = await service.run(db=db, url=url, repo_type=profile)
        # The stored report feeds the Markdown, JSON and comment outputs
        result["report"] = build_report_view(db.get(Analysis, result["analysis_id"]))
        return result
    finally:
        db.close()
        await service.github.aclose()


SEVERITY_COLORS = {
    "critical": "bold red",
    "high": "red",
    "medium": "yellow",
    "low": "cyan",
    "unknown": "white",
}


def print_dependencies(scan_data: dict | None) -> None:
    """Prints the dependency summary and the known vulnerabilities, with what to upgrade to."""
    if not scan_data:
        console.print("\n[bold]Dependencies:[/bold] not scanned for this stored report.")
        return
    scan = DependencyScan.from_dict(scan_data)
    console.print(f"\n[bold]Dependencies:[/bold] {scan.summary_line}")
    for ecosystem, members in scan.by_ecosystem():
        pinned = sum(1 for d in members if d.pinned)
        console.print(f"  {ecosystem}: {len(members)} ({pinned} pinned)")
    for note in scan.notes:
        console.print(f"  [dim]{note}[/dim]")

    if scan.vulnerabilities:
        table = Table(title="Known vulnerabilities", show_header=True, header_style="bold magenta")
        for column in ("Severity", "Package", "Advisory", "Fix"):
            table.add_column(column)
        for v in scan.vulnerabilities:
            color = SEVERITY_COLORS[v.severity]
            fix = f"upgrade to {v.fixed}" if v.fixed else "no fixed version listed"
            table.add_row(f"[{color}]{v.severity}[/{color}]", f"{v.package} {v.version}", v.id, fix)
        console.print(table)
    console.print(f"  [dim]{SCORE_NOTE}[/dim]")


def write_report_files(report: ReportView, directory: Path) -> None:
    """Writes report.md, result.json and comment.md for the GitHub Action to publish."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "report.md").write_text(report_to_markdown(report), encoding="utf-8")
    (directory / "result.json").write_text(
        json.dumps(report_to_summary(report), indent=2), encoding="utf-8"
    )
    (directory / "comment.md").write_text(report_to_comment(report), encoding="utf-8")


def print_rich_report(result: dict) -> None:
    """The terminal report: summary panel, dimension table, findings, dependencies."""
    console.print("\n[bold green]✔ Analysis Complete[/bold green]")

    score = result["score"]

    # Colorize score using the same tiers as the web dashboard
    tier_colors = {"high": "green", "mid": "yellow", "low": "red"}
    score_color = tier_colors[score_tier(score).key]

    # 1. Summary Panel
    summary_text = (
        f"Target: [bold]{result['owner']}/{result['name']}[/bold]\n"
        f"Profile: [bold]{result['repo_type'].capitalize()}[/bold]\n"
        f"Overall Score: [bold {score_color}]{score}/100[/bold {score_color}]\n"
        f"Analysis Duration: {result['duration']}s\n"
        f"Analysis ID: {result['analysis_id']}"
    )
    console.print(Panel(summary_text, title="Executive Summary", expand=False, border_style="cyan"))

    # 2. Dimensions Table
    table = Table(title="Dimensions Breakdown", show_header=True, header_style="bold magenta")
    table.add_column("Dimension")
    table.add_column("Score", justify="right")

    for k, v in result["breakdown"].items():
        if isinstance(v, (int, float)):
            max_v = DIMENSION_MAX_POINTS.get(k, 15)
            dim_color = tier_colors[score_tier(v / max_v * 100).key]
            table.add_row(
                k.capitalize().replace("_", " "), f"[{dim_color}]{v}/{max_v}[/{dim_color}]"
            )

    console.print(table)

    # 3. Findings & Suggestions
    if result.get("strengths"):
        console.print("\n[bold green]Strengths:[/bold green]")
        for item in result["strengths"]:
            console.print(f"  [green]✔[/green] {item}")

    if result.get("weaknesses"):
        console.print("\n[bold red]Areas for Improvement:[/bold red]")
        for item in result["weaknesses"]:
            console.print(f"  [red]✖[/red] {item}")

    if result.get("suggestions"):
        console.print("\n[bold yellow]Actionable Suggestions:[/bold yellow]")
        for i, item in enumerate(result["suggestions"], 1):
            console.print(f"  [bold yellow]{i}.[/bold yellow] {item}")

    print_dependencies(result.get("dependency_scan"))
    console.print("\n")


@app.command()
def analyze(
    url: str = typer.Argument(
        ...,
        help="The public GitHub repository URL to analyze (e.g., https://github.com/fastapi/fastapi)",
    ),
    profile: str = typer.Option(
        "library",
        "--profile",
        "-p",
        help="Repository profile type: 'library', 'personal', or 'enterprise'",
    ),
    output_format: OutputFormat = typer.Option(
        OutputFormat.RICH,
        "--format",
        "-f",
        help="rich (terminal report), markdown or json. The last two print only the report.",
    ),
    min_score: int | None = typer.Option(
        None,
        "--min-score",
        min=0,
        max=100,
        help="Exit with code 2 when the score is below this (the report is still printed).",
    ),
    output_dir: Path | None = typer.Option(
        None,
        "--output-dir",
        help="Also write report.md, result.json and comment.md into this folder.",
    ),
):
    """
    Run an engineering analysis on a GitHub repository.
    """
    rich_output = output_format is OutputFormat.RICH
    # A Markdown or JSON report owns stdout, so messages go to stderr instead
    notify = console if rich_output else err_console
    if rich_output:
        console.print(
            f"[bold cyan]ArchLens CLI[/bold cyan] » Analyzing [bold]{url}[/bold] (Profile: {profile})"
        )

    # Run the analysis with a spinning progress indicator
    spinner = (
        console.status(
            "[bold green]Fetching repository data and running analysis...", spinner="dots"
        )
        if rich_output
        else nullcontext()
    )
    with spinner:
        try:
            result = asyncio.run(async_analyze(url, profile))
        except InvalidRepositoryURLError:
            notify.print(
                f"[bold red]Error:[/bold red] Invalid GitHub repository URL provided: {url}"
            )
            raise typer.Exit(code=EXIT_ERROR)
        except RepositoryNotFoundError as e:
            notify.print(f"[bold red]Error:[/bold red] {str(e)}")
            raise typer.Exit(code=EXIT_ERROR)
        except RateLimitExceededError as e:
            notify.print(
                f"[bold red]Error:[/bold red] GitHub API rate limit exceeded. Reset time: {e.reset_epoch}"
            )
            raise typer.Exit(code=EXIT_ERROR)
        except ArchLensError as e:
            notify.print(f"[bold red]Error:[/bold red] {e.message}")
            raise typer.Exit(code=EXIT_ERROR)
        except Exception as e:
            notify.print(f"[bold red]Error:[/bold red] An unexpected error occurred: {str(e)}")
            raise typer.Exit(code=EXIT_ERROR)

    report = result.get("report")
    if output_dir is not None and report is not None:
        write_report_files(report, output_dir)

    if output_format is OutputFormat.MARKDOWN:
        typer.echo(report_to_markdown(report))
    elif output_format is OutputFormat.JSON:
        typer.echo(json.dumps(report_to_summary(report), indent=2))
    else:
        print_rich_report(result)

    if min_score is not None and result["score"] < min_score:
        notify.print(
            f"[bold red]Score {result['score']} is below the minimum of {min_score}.[/bold red]"
        )
        raise typer.Exit(code=EXIT_BELOW_MIN_SCORE)


if __name__ == "__main__":
    app()
