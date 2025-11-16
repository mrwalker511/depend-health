"""
Comprehensive audit functionality for requirements analysis

This module provides comprehensive auditing of all packages in requirements.txt,
including health checks, outdated version detection, and statistics.
"""

import asyncio
import logging
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timezone
from rich.table import Table
from rich.console import Console
from packaging.version import Version, InvalidVersion

from .models import HealthReport
from .health import check_health
from .services import APIClient
from .resolver import get_local_requirements

logger = logging.getLogger(__name__)


class AuditResult:
    """Results from auditing a single package"""
    def __init__(
        self,
        package_name: str,
        current_version: Optional[str],
        health_report: Optional[HealthReport],
        latest_version: Optional[str],
        is_outdated: bool,
        error: Optional[str] = None
    ):
        self.package_name = package_name
        self.current_version = current_version
        self.health_report = health_report
        self.latest_version = latest_version
        self.is_outdated = is_outdated
        self.error = error


class AuditSummary:
    """Summary statistics from auditing requirements"""
    def __init__(self):
        self.total_packages = 0
        self.healthy_packages = 0
        self.slow_packages = 0
        self.zombie_packages = 0
        self.outdated_packages = 0
        self.error_packages = 0
        self.packages_with_github = 0
        self.total_stars = 0
        self.total_open_issues = 0


async def audit_package(package_name: str, current_version: Optional[str]) -> AuditResult:
    """
    Audit a single package for health and version status

    Args:
        package_name: Name of the package
        current_version: Currently installed/specified version

    Returns:
        AuditResult with health and version information
    """
    try:
        logger.info(f"Auditing package: {package_name}")

        # Get health report
        health_report = await check_health(package_name)

        # Check if outdated
        latest_version = health_report.pypi.version
        is_outdated = False

        if current_version and latest_version:
            try:
                current_ver = Version(current_version)
                latest_ver = Version(latest_version)
                is_outdated = current_ver < latest_ver
            except InvalidVersion:
                logger.warning(f"Could not compare versions for {package_name}")

        return AuditResult(
            package_name=package_name,
            current_version=current_version,
            health_report=health_report,
            latest_version=latest_version,
            is_outdated=is_outdated
        )

    except Exception as e:
        logger.error(f"Error auditing {package_name}: {e}")
        return AuditResult(
            package_name=package_name,
            current_version=current_version,
            health_report=None,
            latest_version=None,
            is_outdated=False,
            error=str(e)
        )


async def audit_requirements(
    filepath: str,
    max_concurrent: int = 5
) -> Tuple[List[AuditResult], AuditSummary]:
    """
    Audit all packages in a requirements file

    Args:
        filepath: Path to requirements.txt
        max_concurrent: Maximum concurrent API requests

    Returns:
        Tuple of (list of audit results, summary statistics)
    """
    # Parse requirements
    requirements = get_local_requirements(filepath)

    if not requirements:
        logger.warning(f"No requirements found in {filepath}")
        return [], AuditSummary()

    logger.info(f"Auditing {len(requirements)} packages from {filepath}")

    # Create semaphore to limit concurrent requests
    semaphore = asyncio.Semaphore(max_concurrent)

    async def audit_with_semaphore(pkg_name: str, version: Optional[str]) -> AuditResult:
        async with semaphore:
            return await audit_package(pkg_name, version)

    # Audit all packages concurrently (with limit)
    tasks = []
    for req in requirements:
        # Extract version if specified
        current_version = None
        if req.specifier:
            # Try to extract a specific version (e.g., ==2.0.0)
            for spec in req.specifier:
                spec_str = str(spec)
                if spec_str.startswith('=='):
                    current_version = spec_str[2:]
                    break

        tasks.append(audit_with_semaphore(req.name, current_version))

    results = await asyncio.gather(*tasks)

    # Calculate summary statistics
    summary = AuditSummary()
    summary.total_packages = len(results)

    for result in results:
        if result.error:
            summary.error_packages += 1
            continue

        if result.health_report:
            status = result.health_report.health_status
            if status == "Active":
                summary.healthy_packages += 1
            elif status == "Slow":
                summary.slow_packages += 1
            elif status == "Zombie":
                summary.zombie_packages += 1

            if result.health_report.github:
                summary.packages_with_github += 1
                summary.total_stars += result.health_report.github.stars
                summary.total_open_issues += result.health_report.github.open_issues

        if result.is_outdated:
            summary.outdated_packages += 1

    return results, summary


def create_audit_table(results: List[AuditResult], show_all: bool = False) -> Table:
    """
    Create a rich Table displaying audit results

    Args:
        results: List of audit results
        show_all: If True, show all packages. If False, only show issues

    Returns:
        Rich Table object
    """
    table = Table(title="📋 Package Audit Report")

    table.add_column("Package", style="cyan", no_wrap=True)
    table.add_column("Current", style="dim")
    table.add_column("Latest", style="green")
    table.add_column("Status", style="bold")
    table.add_column("Health", justify="center")
    table.add_column("Stars", justify="right", style="yellow")
    table.add_column("Issues", justify="right", style="red")

    for result in results:
        if result.error:
            table.add_row(
                result.package_name,
                result.current_version or "?",
                "ERROR",
                "❌ Error",
                "-",
                "-",
                "-"
            )
            continue

        if not result.health_report:
            continue

        # Filter if not showing all
        if not show_all:
            if result.health_report.health_status == "Active" and not result.is_outdated:
                continue

        # Determine status emoji
        status_emoji = {
            "Active": "✅",
            "Slow": "⚠️",
            "Zombie": "❌"
        }.get(result.health_report.health_status, "❓")

        # Version status
        version_status = "🔄 Outdated" if result.is_outdated else "✅ Current"

        # GitHub stats
        github_stars = "-"
        github_issues = "-"
        if result.health_report.github:
            github_stars = f"{result.health_report.github.stars:,}"
            github_issues = str(result.health_report.github.open_issues)

        table.add_row(
            result.package_name,
            result.current_version or "latest",
            result.latest_version or "?",
            version_status,
            f"{status_emoji} {result.health_report.health_status}",
            github_stars,
            github_issues
        )

    return table


def create_summary_panel(summary: AuditSummary) -> str:
    """
    Create a summary text from audit statistics

    Args:
        summary: AuditSummary object

    Returns:
        Formatted summary string
    """
    lines = []
    lines.append(f"Total Packages: {summary.total_packages}")
    lines.append("")
    lines.append("Health Status:")
    lines.append(f"  ✅ Active: {summary.healthy_packages}")
    lines.append(f"  ⚠️  Slow: {summary.slow_packages}")
    lines.append(f"  ❌ Zombie: {summary.zombie_packages}")

    if summary.error_packages > 0:
        lines.append(f"  ❗ Errors: {summary.error_packages}")

    lines.append("")
    lines.append(f"🔄 Outdated: {summary.outdated_packages}")
    lines.append(f"💻 With GitHub: {summary.packages_with_github}")

    if summary.packages_with_github > 0:
        lines.append("")
        lines.append("GitHub Stats:")
        lines.append(f"  ⭐ Total Stars: {summary.total_stars:,}")
        lines.append(f"  🐛 Total Issues: {summary.total_open_issues:,}")

    return "\n".join(lines)


async def get_outdated_packages(filepath: str) -> List[Tuple[str, str, str]]:
    """
    Get list of outdated packages from requirements file

    Args:
        filepath: Path to requirements.txt

    Returns:
        List of tuples (package_name, current_version, latest_version)
    """
    results, _ = await audit_requirements(filepath)

    outdated = []
    for result in results:
        if result.is_outdated and result.current_version and result.latest_version:
            outdated.append((
                result.package_name,
                result.current_version,
                result.latest_version
            ))

    return outdated


def calculate_requirements_stats(filepath: str) -> Dict[str, any]:
    """
    Calculate statistics about requirements file

    Args:
        filepath: Path to requirements.txt

    Returns:
        Dictionary of statistics
    """
    requirements = get_local_requirements(filepath)

    stats = {
        "total_packages": len(requirements),
        "pinned_versions": 0,
        "version_ranges": 0,
        "unpinned": 0
    }

    for req in requirements:
        if not req.specifier:
            stats["unpinned"] += 1
        elif any(str(spec).startswith('==') for spec in req.specifier):
            stats["pinned_versions"] += 1
        else:
            stats["version_ranges"] += 1

    return stats
