"""
Main CLI application
"""

import typer
import asyncio
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typing import Optional
import httpx

from .health import check_health, format_relative_date
from .models import HealthReport

app = typer.Typer(
    name="dep-manager",
    help="Dependency Manager - Check the health of your Python packages",
    add_completion=False
)

console = Console()


def format_health_report(report: HealthReport) -> Panel:
    """
    Format a health report as a rich Panel

    Args:
        report: HealthReport to format

    Returns:
        Rich Panel with formatted output
    """
    # Title with package name and version
    title = f"🩺 Health Report for: {report.pypi.name} ({report.pypi.version})"

    # Build the content
    lines = []

    # Summary and license
    lines.append(f"Summary: {report.pypi.summary}")
    lines.append(f"License: {report.pypi.license}")
    lines.append("")

    # PyPI stats
    lines.append("📦 PyPI Stats")
    release_date_str = report.pypi.release_date.strftime("%Y-%m-%d")
    relative_release = format_relative_date(report.pypi.release_date)
    lines.append(f"├── Latest Release: {release_date_str} ({relative_release})")
    lines.append("└── Vulnerabilities: 0 known")
    lines.append("")

    # GitHub stats (if available)
    if report.github:
        lines.append(f"💻 GitHub Stats ({report.github.repo_name})")
        commit_date_str = report.github.pushed_at.strftime("%Y-%m-%d")
        relative_commit = format_relative_date(report.github.pushed_at)
        lines.append(f"├── Last Commit: {commit_date_str} ({relative_commit})")
        lines.append(f"├── Open Issues: {report.github.open_issues:,}")
        lines.append(f"└── Stars: {report.github.stars:,}")
        lines.append("")

    # Recommendation with emoji based on status
    status_emoji = {
        "Active": "✅",
        "Slow": "⚠️",
        "Zombie": "❌"
    }
    emoji = status_emoji.get(report.health_status, "ℹ️")
    lines.append(f"{emoji} Recommendation: {report.recommendation}")

    content = "\n".join(lines)

    # Create colored panel based on health status
    border_style = {
        "Active": "green",
        "Slow": "yellow",
        "Zombie": "red"
    }.get(report.health_status, "blue")

    return Panel(
        content,
        title=title,
        title_align="left",
        border_style=border_style,
        padding=(1, 2)
    )


@app.command()
def health(
    package_name: str = typer.Argument(..., help="Name of the Python package to check")
):
    """
    Check the health of a Python package

    Fetches information from PyPI and GitHub to assess package health,
    activity, and maintenance status.
    """
    try:
        with console.status(
            f"[bold blue]Checking health of '{package_name}'...",
            spinner="dots"
        ):
            # Run async health check
            report = asyncio.run(check_health(package_name))

        # Display the report
        panel = format_health_report(report)
        console.print()
        console.print(panel)
        console.print()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print()
            console.print(
                f"[bold red]❌ Package '{package_name}' not found on PyPI[/bold red]"
            )
            console.print()
            raise typer.Exit(code=1)
        else:
            console.print()
            console.print(f"[bold red]❌ HTTP Error: {e}[/bold red]")
            console.print()
            raise typer.Exit(code=1)

    except Exception as e:
        console.print()
        console.print(f"[bold red]❌ Error: {e}[/bold red]")
        console.print()
        raise typer.Exit(code=1)


@app.command()
def version():
    """Show the version of dep-manager"""
    from . import __version__
    console.print(f"dep-manager version {__version__}")


if __name__ == "__main__":
    app()
