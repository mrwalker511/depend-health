"""
Package comparison functionality

This module provides side-by-side comparison of two packages
to help choose between alternatives.
"""

import asyncio
import logging
from typing import Tuple
from rich.table import Table
from rich.console import Console

from .models import HealthReport
from .health import check_health, format_relative_date

logger = logging.getLogger(__name__)


class ComparisonResult:
    """Results from comparing two packages"""
    def __init__(self, package1: HealthReport, package2: HealthReport):
        self.package1 = package1
        self.package2 = package2


async def compare_packages(package1_name: str, package2_name: str) -> ComparisonResult:
    """
    Compare two packages side-by-side

    Args:
        package1_name: Name of first package
        package2_name: Name of second package

    Returns:
        ComparisonResult with both health reports
    """
    logger.info(f"Comparing {package1_name} vs {package2_name}")

    # Fetch both packages concurrently
    health1, health2 = await asyncio.gather(
        check_health(package1_name),
        check_health(package2_name)
    )

    return ComparisonResult(health1, health2)


def create_comparison_table(result: ComparisonResult) -> Table:
    """
    Create a rich Table showing side-by-side comparison

    Args:
        result: ComparisonResult object

    Returns:
        Rich Table object
    """
    table = Table(title="📊 Package Comparison")

    table.add_column("Metric", style="cyan", no_wrap=True)
    table.add_column(result.package1.pypi.name, style="green")
    table.add_column(result.package2.pypi.name, style="blue")
    table.add_column("Winner", style="bold yellow")

    # Basic info
    table.add_row(
        "Latest Version",
        result.package1.pypi.version,
        result.package2.pypi.version,
        "-"
    )

    table.add_row(
        "License",
        result.package1.pypi.license or "Unknown",
        result.package2.pypi.license or "Unknown",
        "-"
    )

    # Release freshness
    rel1_str = format_relative_date(result.package1.pypi.release_date)
    rel2_str = format_relative_date(result.package2.pypi.release_date)
    rel_winner = _compare_dates(
        result.package1.pypi.release_date,
        result.package2.pypi.release_date,
        result.package1.pypi.name,
        result.package2.pypi.name
    )

    table.add_row(
        "Last Release",
        rel1_str,
        rel2_str,
        rel_winner
    )

    # Health status
    status1 = result.package1.health_status
    status2 = result.package2.health_status
    status_winner = _compare_health(
        status1,
        status2,
        result.package1.pypi.name,
        result.package2.pypi.name
    )

    table.add_row(
        "Health Status",
        f"{_get_status_emoji(status1)} {status1}",
        f"{_get_status_emoji(status2)} {status2}",
        status_winner
    )

    # GitHub stats (if available)
    if result.package1.github or result.package2.github:
        table.add_row("", "", "", "", style="dim")  # Separator
        table.add_row("[bold]GitHub Stats", "", "", "", style="bold")

        # Repository
        repo1 = result.package1.github.repo_name if result.package1.github else "N/A"
        repo2 = result.package2.github.repo_name if result.package2.github else "N/A"
        table.add_row("Repository", repo1, repo2, "-")

        # Stars
        if result.package1.github and result.package2.github:
            stars1 = result.package1.github.stars
            stars2 = result.package2.github.stars
            stars_winner = result.package1.pypi.name if stars1 > stars2 else result.package2.pypi.name

            table.add_row(
                "⭐ Stars",
                f"{stars1:,}",
                f"{stars2:,}",
                f"🏆 {stars_winner}"
            )

            # Issues
            issues1 = result.package1.github.open_issues
            issues2 = result.package2.github.open_issues
            # Fewer issues is better
            issues_winner = result.package1.pypi.name if issues1 < issues2 else result.package2.pypi.name

            table.add_row(
                "🐛 Open Issues",
                str(issues1),
                str(issues2),
                f"🏆 {issues_winner}"
            )

            # Last commit
            commit1_str = format_relative_date(result.package1.github.pushed_at)
            commit2_str = format_relative_date(result.package2.github.pushed_at)
            commit_winner = _compare_dates(
                result.package1.github.pushed_at,
                result.package2.github.pushed_at,
                result.package1.pypi.name,
                result.package2.pypi.name
            )

            table.add_row(
                "Last Commit",
                commit1_str,
                commit2_str,
                commit_winner
            )

    # Overall recommendation
    table.add_row("", "", "", "", style="dim")  # Separator
    overall_winner = _determine_overall_winner(result)
    table.add_row(
        "[bold]Overall Recommendation",
        "",
        "",
        f"🏆 {overall_winner}",
        style="bold green"
    )

    return table


def _get_status_emoji(status: str) -> str:
    """Get emoji for health status"""
    return {
        "Active": "✅",
        "Slow": "⚠️",
        "Zombie": "❌"
    }.get(status, "❓")


def _compare_dates(date1, date2, name1, name2) -> str:
    """Compare two dates and return winner (more recent is better)"""
    if date1 > date2:
        return f"🏆 {name1}"
    elif date2 > date1:
        return f"🏆 {name2}"
    return "Tie"


def _compare_health(status1, status2, name1, name2) -> str:
    """Compare health statuses"""
    health_rank = {"Active": 3, "Slow": 2, "Zombie": 1}
    rank1 = health_rank.get(status1, 0)
    rank2 = health_rank.get(status2, 0)

    if rank1 > rank2:
        return f"🏆 {name1}"
    elif rank2 > rank1:
        return f"🏆 {name2}"
    return "Tie"


def _determine_overall_winner(result: ComparisonResult) -> str:
    """
    Determine overall winner based on multiple factors

    Scoring:
    - Health status: Active=3, Slow=2, Zombie=1
    - Stars: logarithmic scale
    - Recent activity: bonus points
    """
    score1 = 0
    score2 = 0

    # Health status
    health_rank = {"Active": 3, "Slow": 2, "Zombie": 1}
    score1 += health_rank.get(result.package1.health_status, 0) * 10
    score2 += health_rank.get(result.package2.health_status, 0) * 10

    # GitHub stars (logarithmic to prevent huge differences)
    if result.package1.github:
        score1 += min(result.package1.github.stars / 1000, 10)
    if result.package2.github:
        score2 += min(result.package2.github.stars / 1000, 10)

    # Recent activity
    if result.package1.days_since_release < 90:
        score1 += 5
    if result.package2.days_since_release < 90:
        score2 += 5

    if result.package1.github and result.package1.days_since_commit and result.package1.days_since_commit < 90:
        score1 += 5
    if result.package2.github and result.package2.days_since_commit and result.package2.days_since_commit < 90:
        score2 += 5

    # Determine winner
    if score1 > score2:
        return result.package1.pypi.name
    elif score2 > score1:
        return result.package2.pypi.name
    return "Tie - Both are good choices!"
