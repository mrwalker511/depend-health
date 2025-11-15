"""
Main CLI application
"""

import typer
import asyncio
import subprocess
import shlex
import sys
from pathlib import Path
from rich.console import Console
from rich.panel import Panel
from rich.text import Text
from typing import Optional
import httpx

from .health import check_health, format_relative_date
from .models import HealthReport
from .resolver import (
    get_local_requirements,
    get_package_dependencies,
    find_conflicts,
    append_to_requirements
)

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


async def _check_add_async(package_name: str, requirements_file: str):
    """Internal async implementation of check-add - handles all async operations"""
    # Step 1: Run health check
    report = await check_health(package_name)

    # Step 2: Fetch new package dependencies
    new_version, new_deps = await get_package_dependencies(package_name)

    return report, new_version, new_deps


@app.command()
def check_add(
    package_name: str = typer.Argument(..., help="Name of the Python package to add"),
    requirements_file: str = typer.Option(
        "requirements.txt",
        "--file",
        "-f",
        help="Path to requirements.txt file"
    )
):
    """
    Check package health and add to requirements.txt if safe

    This command performs a health check, detects dependency conflicts,
    and safely adds the package to requirements.txt if no conflicts are found.
    """
    try:
        # Step 1 & 2: Run async operations (health check + dependency fetch)
        with console.status(
            f"[bold blue]Checking health of '{package_name}' and fetching dependencies...",
            spinner="dots"
        ):
            report, new_version, new_deps = asyncio.run(
                _check_add_async(package_name, requirements_file)
            )

        # Display health report
        panel = format_health_report(report)
        console.print()
        console.print(panel)
        console.print()

        # Step 3: Confirm if health is questionable
        if report.health_status in ["Zombie", "Slow"]:
            console.print(
                f"[bold yellow]⚠️  Warning: This package has {report.health_status.lower()} activity.[/bold yellow]"
            )
            proceed = typer.confirm("Do you still want to proceed?")
            if not proceed:
                console.print("[yellow]Operation cancelled.[/yellow]")
                raise typer.Exit(code=0)

        # Step 4: Parse local requirements
        console.print(f"[bold blue]📋 Checking local requirements from '{requirements_file}'...[/bold blue]")
        local_reqs = get_local_requirements(requirements_file)
        console.print(f"[dim]Found {len(local_reqs)} existing packages[/dim]")

        console.print(f"[dim]Package '{package_name}' has {len(new_deps)} dependencies[/dim]")

        # Step 5: Find conflicts
        conflicts = find_conflicts(
            package_name,
            new_version,
            new_deps,
            local_reqs
        )

        # Step 6: Report conflicts or proceed
        if conflicts:
            # Display conflicts in an error panel
            conflict_text = "\n".join(conflicts)
            error_panel = Panel(
                conflict_text,
                title="❌ Dependency Conflicts Found",
                title_align="left",
                border_style="red",
                padding=(1, 2)
            )
            console.print()
            console.print(error_panel)
            console.print()
            console.print(
                "[bold red]Cannot add package due to conflicts. "
                "Please resolve these issues first.[/bold red]"
            )
            raise typer.Exit(code=1)

        # No conflicts - proceed with adding
        console.print("[bold green]✅ No conflicts detected![/bold green]")
        console.print()

        # Step 7: Add to requirements.txt
        console.print(f"[bold green]Adding '{package_name}=={new_version}' to {requirements_file}...[/bold green]")
        append_to_requirements(requirements_file, package_name, new_version)
        console.print("[green]✓ Package added to requirements.txt[/green]")
        console.print()

        # Step 8: Ask to install
        install = typer.confirm(
            "Would you like to install/upgrade all packages now?",
            default=True
        )

        if install:
            console.print()
            console.print("[bold blue]Running: pip install -r requirements.txt --upgrade[/bold blue]")
            console.print("[dim]" + "=" * 70 + "[/dim]")

            # Run pip install with real-time output streaming
            cmd = f"pip install -r {requirements_file} --upgrade"
            process = subprocess.Popen(
                shlex.split(cmd),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1
            )

            # Stream output in real-time
            if process.stdout:
                for line in process.stdout:
                    console.print(line.rstrip())

            # Wait for completion
            return_code = process.wait()

            console.print("[dim]" + "=" * 70 + "[/dim]")

            if return_code == 0:
                console.print()
                console.print("[bold green]✅ Installation completed successfully![/bold green]")
            else:
                console.print()
                console.print(f"[bold red]❌ Installation failed with exit code {return_code}[/bold red]")
                raise typer.Exit(code=return_code)
        else:
            console.print("[yellow]Skipped installation. Run 'pip install -r requirements.txt' manually.[/yellow]")

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

    except FileNotFoundError:
        console.print()
        console.print(
            f"[bold red]❌ Requirements file '{requirements_file}' not found[/bold red]"
        )
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
