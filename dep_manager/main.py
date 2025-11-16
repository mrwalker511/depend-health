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
from .audit import (
    audit_requirements,
    create_audit_table,
    create_summary_panel,
    get_outdated_packages,
    calculate_requirements_stats
)
from .compare import compare_packages, create_comparison_table
from .search import search_pypi, create_search_table

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
def audit(
    requirements_file: str = typer.Option(
        "requirements.txt",
        "--file",
        "-f",
        help="Path to requirements.txt file"
    ),
    show_all: bool = typer.Option(
        False,
        "--all",
        "-a",
        help="Show all packages, not just issues"
    )
):
    """
    Comprehensive audit of all packages in requirements.txt

    Checks health, outdated status, and generates statistics for all
    packages in your requirements file.
    """
    try:
        with console.status(
            f"[bold blue]Auditing packages in '{requirements_file}'...",
            spinner="dots"
        ):
            results, summary = asyncio.run(audit_requirements(requirements_file))

        if not results:
            console.print()
            console.print("[yellow]No packages found to audit.[/yellow]")
            console.print()
            return

        # Display audit table
        table = create_audit_table(results, show_all=show_all)
        console.print()
        console.print(table)
        console.print()

        # Display summary panel
        summary_text = create_summary_panel(summary)
        summary_panel = Panel(
            summary_text,
            title="📊 Audit Summary",
            title_align="left",
            border_style="blue",
            padding=(1, 2)
        )
        console.print(summary_panel)
        console.print()

        # Provide recommendations
        if summary.zombie_packages > 0:
            console.print("[bold red]⚠️  Warning: Some packages have low activity (Zombie status)[/bold red]")
        if summary.outdated_packages > 0:
            console.print(f"[bold yellow]🔄 {summary.outdated_packages} package(s) have updates available[/bold yellow]")
        if summary.healthy_packages == summary.total_packages - summary.error_packages:
            console.print("[bold green]✅ All packages are healthy![/bold green]")

        console.print()

    except FileNotFoundError:
        console.print()
        console.print(f"[bold red]❌ Requirements file '{requirements_file}' not found[/bold red]")
        console.print()
        raise typer.Exit(code=1)

    except Exception as e:
        console.print()
        console.print(f"[bold red]❌ Error: {e}[/bold red]")
        console.print()
        raise typer.Exit(code=1)


@app.command()
def compare(
    package1: str = typer.Argument(..., help="First package name"),
    package2: str = typer.Argument(..., help="Second package name")
):
    """
    Compare two packages side-by-side

    Compares health status, GitHub stats, and other metrics to help
    you choose between alternative packages.
    """
    try:
        with console.status(
            f"[bold blue]Comparing '{package1}' vs '{package2}'...",
            spinner="dots"
        ):
            result = asyncio.run(compare_packages(package1, package2))

        # Display comparison table
        table = create_comparison_table(result)
        console.print()
        console.print(table)
        console.print()

    except httpx.HTTPStatusError as e:
        if e.response.status_code == 404:
            console.print()
            console.print("[bold red]❌ One or both packages not found on PyPI[/bold red]")
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
def outdated(
    requirements_file: str = typer.Option(
        "requirements.txt",
        "--file",
        "-f",
        help="Path to requirements.txt file"
    )
):
    """
    List packages with newer versions available

    Quickly check which packages in your requirements.txt have
    updates available on PyPI.
    """
    try:
        with console.status(
            f"[bold blue]Checking for outdated packages in '{requirements_file}'...",
            spinner="dots"
        ):
            outdated_list = asyncio.run(get_outdated_packages(requirements_file))

        if not outdated_list:
            console.print()
            console.print("[bold green]✅ All packages are up to date![/bold green]")
            console.print()
            return

        # Create table
        table = Table(title=f"🔄 Outdated Packages ({len(outdated_list)} found)")
        table.add_column("Package", style="cyan bold")
        table.add_column("Current", style="red")
        table.add_column("Latest", style="green bold")
        table.add_column("Update Command", style="dim")

        for pkg_name, current, latest in outdated_list:
            table.add_row(
                pkg_name,
                current,
                latest,
                f"pip install {pkg_name}=={latest}"
            )

        console.print()
        console.print(table)
        console.print()
        console.print(f"[dim]Run 'pip install --upgrade <package>' to update[/dim]")
        console.print()

    except FileNotFoundError:
        console.print()
        console.print(f"[bold red]❌ Requirements file '{requirements_file}' not found[/bold red]")
        console.print()
        raise typer.Exit(code=1)

    except Exception as e:
        console.print()
        console.print(f"[bold red]❌ Error: {e}[/bold red]")
        console.print()
        raise typer.Exit(code=1)


@app.command()
def search(
    query: str = typer.Argument(..., help="Search query"),
    limit: int = typer.Option(10, "--limit", "-n", help="Maximum number of results")
):
    """
    Search PyPI for packages

    Search for packages on PyPI by keyword or package name.
    """
    try:
        with console.status(
            f"[bold blue]Searching PyPI for '{query}'...",
            spinner="dots"
        ):
            results = asyncio.run(search_pypi(query, limit))

        if not results:
            console.print()
            console.print(f"[yellow]No packages found matching '{query}'[/yellow]")
            console.print()
            console.print("[dim]Try a different search term or check spelling[/dim]")
            console.print()
            return

        # Display results table
        table = create_search_table(results, query)
        console.print()
        console.print(table)
        console.print()
        console.print(f"[dim]Found {len(results)} package(s). Use 'dep-manager health <package>' for details.[/dim]")
        console.print()

    except Exception as e:
        console.print()
        console.print(f"[bold red]❌ Error: {e}[/bold red]")
        console.print()
        raise typer.Exit(code=1)


@app.command()
def stats(
    requirements_file: str = typer.Option(
        "requirements.txt",
        "--file",
        "-f",
        help="Path to requirements.txt file"
    )
):
    """
    Show statistics about your requirements.txt

    Displays statistics about version pinning, package count, and
    requirements file structure.
    """
    try:
        stats_data = calculate_requirements_stats(requirements_file)

        # Create display panel
        lines = []
        lines.append(f"File: {requirements_file}")
        lines.append("")
        lines.append(f"Total Packages: {stats_data['total_packages']}")
        lines.append("")
        lines.append("Version Specification:")
        lines.append(f"  📌 Pinned (==): {stats_data['pinned_versions']}")
        lines.append(f"  📊 Range (>=, ~=): {stats_data['version_ranges']}")
        lines.append(f"  🔓 Unpinned: {stats_data['unpinned']}")

        panel = Panel(
            "\n".join(lines),
            title="📈 Requirements Statistics",
            title_align="left",
            border_style="blue",
            padding=(1, 2)
        )

        console.print()
        console.print(panel)
        console.print()

        # Provide recommendations
        if stats_data['unpinned'] > 0:
            console.print("[yellow]⚠️  Consider pinning versions for reproducible builds[/yellow]")

    except FileNotFoundError:
        console.print()
        console.print(f"[bold red]❌ Requirements file '{requirements_file}' not found[/bold red]")
        console.print()
        raise typer.Exit(code=1)

    except Exception as e:
        console.print()
        console.print(f"[bold red]❌ Error: {e}[/bold red]")
        console.print()
        raise typer.Exit(code=1)


@app.command()
def remove(
    package_name: str = typer.Argument(..., help="Name of package to remove"),
    requirements_file: str = typer.Option(
        "requirements.txt",
        "--file",
        "-f",
        help="Path to requirements.txt file"
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Skip confirmation prompt"
    )
):
    """
    Safely remove a package from requirements.txt

    Removes a package from requirements.txt with confirmation.
    Does not uninstall the package - use pip uninstall for that.
    """
    try:
        # Check if package exists
        requirements = get_local_requirements(requirements_file)
        normalized_name = package_name.lower().replace('-', '_')

        found_req = None
        for req in requirements:
            if req.name.lower().replace('-', '_') == normalized_name:
                found_req = req
                break

        if not found_req:
            console.print()
            console.print(f"[yellow]Package '{package_name}' not found in {requirements_file}[/yellow]")
            console.print()
            return

        # Confirm removal
        if not force:
            console.print()
            console.print(f"[yellow]Remove '{found_req}' from {requirements_file}?[/yellow]")
            confirmed = typer.confirm("Continue?")
            if not confirmed:
                console.print("[dim]Cancelled.[/dim]")
                return

        # Remove from file
        with open(requirements_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        with open(requirements_file, 'w', encoding='utf-8') as f:
            for line in lines:
                line_stripped = line.strip()
                if line_stripped and not line_stripped.startswith('#'):
                    try:
                        from packaging.requirements import Requirement
                        req = Requirement(line_stripped)
                        if req.name.lower().replace('-', '_') == normalized_name:
                            continue  # Skip this line
                    except:
                        pass
                f.write(line)

        console.print()
        console.print(f"[green]✓ Removed '{found_req}' from {requirements_file}[/green]")
        console.print()
        console.print(f"[dim]Note: Package is still installed. Run 'pip uninstall {package_name}' to uninstall.[/dim]")
        console.print()

    except FileNotFoundError:
        console.print()
        console.print(f"[bold red]❌ Requirements file '{requirements_file}' not found[/bold red]")
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
