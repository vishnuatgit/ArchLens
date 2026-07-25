import asyncio
import sys

# Force UTF-8 encoding for Windows console (fixes UnicodeEncodeError for checkmarks)
if sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from app.exceptions import (
    InvalidRepositoryURLError,
    RateLimitExceededError,
    RepositoryNotFoundError,
)
from app.repositories.db import SessionLocal
from app.services.analysis_service import AnalysisService

app = typer.Typer(help="ArchLens CLI - AI-Powered Repository Intelligence Engine")
console = Console()


async def async_analyze(url: str, profile: str) -> dict:
    """Async wrapper to run the AnalysisService."""
    service = AnalysisService()
    # Provide the database session
    db = SessionLocal()
    try:
        # Run the full pipeline
        return await service.run(db=db, url=url, repo_type=profile)
    finally:
        db.close()


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
):
    """
    Run an engineering analysis on a GitHub repository.
    """
    console.print(
        f"[bold cyan]ArchLens CLI[/bold cyan] » Analyzing [bold]{url}[/bold] (Profile: {profile})"
    )

    # Run the analysis with a spinning progress indicator
    with console.status(
        "[bold green]Fetching repository data and running analysis...", spinner="dots"
    ):
        try:
            result = asyncio.run(async_analyze(url, profile))
        except InvalidRepositoryURLError:
            console.print(
                f"[bold red]Error:[/bold red] Invalid GitHub repository URL provided: {url}"
            )
            raise typer.Exit(code=1)
        except RepositoryNotFoundError as e:
            console.print(f"[bold red]Error:[/bold red] {str(e)}")
            raise typer.Exit(code=1)
        except RateLimitExceededError as e:
            console.print(
                f"[bold red]Error:[/bold red] GitHub API rate limit exceeded. Reset time: {e.reset_time}"
            )
            raise typer.Exit(code=1)
        except Exception as e:
            console.print(f"[bold red]Error:[/bold red] An unexpected error occurred: {str(e)}")
            raise typer.Exit(code=1)

    # Output formatting
    console.print("\n[bold green]✔ Analysis Complete[/bold green]")

    score = result["score"]

    # Colorize score
    score_color = "green" if score >= 70 else "yellow" if score >= 40 else "red"

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
            dim_color = "green" if v >= 7 else "yellow" if v >= 4 else "red"
            table.add_row(k.capitalize().replace("_", " "), f"[{dim_color}]{v}/10[/{dim_color}]")

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

    console.print("\n")


if __name__ == "__main__":
    app()
