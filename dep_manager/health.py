"""
Health check logic for packages

This module provides health checking functionality by analyzing
PyPI and GitHub data in parallel for optimal performance.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, Tuple
from .services import APIClient
from .models import PyPIInfo, GitHubInfo, HealthReport

logger = logging.getLogger(__name__)


async def check_health(package_name: str) -> HealthReport:
    """
    Check the health of a package by fetching PyPI and GitHub data in parallel

    Args:
        package_name: Name of the package to check

    Returns:
        HealthReport containing all health information

    Raises:
        httpx.HTTPStatusError: If package not found
        Exception: For other errors
    """
    # Use client as context manager for connection pooling
    async with APIClient() as client:
        # Fetch PyPI data first
        logger.info(f"Starting health check for package: {package_name}")
        pypi_data = await client.fetch_pypi_info(package_name)

        # Parse PyPI information
        info = pypi_data["info"]

        # Get the latest version and its release date
        version = info["version"]
        releases = pypi_data.get("releases", {})
        release_info = releases.get(version, [])

        # Get release date from the first file in the release
        release_date = datetime.now(timezone.utc)
        if release_info and len(release_info) > 0:
            upload_time = release_info[0].get("upload_time_iso_8601")
            if upload_time:
                release_date = datetime.fromisoformat(upload_time.replace('Z', '+00:00'))

        # Get license
        license_info = info.get("license") or "Unknown"

        pypi_info = PyPIInfo(
            name=info["name"],
            version=version,
            summary=info.get("summary", "No description available"),
            license=license_info,
            release_date=release_date,
            project_urls=info.get("project_urls")
        )

        # Try to fetch GitHub data
        github_info = None
        days_since_commit = None

        github_repo = client.extract_github_repo(pypi_data)

        if github_repo:
            owner, repo = github_repo
            try:
                github_data = await client.fetch_github_info(owner, repo)

                pushed_at = datetime.fromisoformat(
                    github_data["pushed_at"].replace('Z', '+00:00')
                )

                github_info = GitHubInfo(
                    repo_name=f"{owner}/{repo}",
                    pushed_at=pushed_at,
                    open_issues=github_data["open_issues_count"],
                    stars=github_data["stargazers_count"]
                )

                days_since_commit = (datetime.now(timezone.utc) - pushed_at).days
                logger.info(f"Successfully fetched GitHub data for {owner}/{repo}")

            except Exception as e:
                # If GitHub fetch fails, continue without it
                logger.warning(f"Failed to fetch GitHub data for {owner}/{repo}: {e}")
                pass

    # Calculate health status
    days_since_release = (datetime.now(timezone.utc) - release_date).days
    health_status, recommendation = calculate_health_status(
        days_since_commit, days_since_release
    )

    return HealthReport(
        pypi=pypi_info,
        github=github_info,
        health_status=health_status,
        recommendation=recommendation,
        days_since_commit=days_since_commit,
        days_since_release=days_since_release
    )


def calculate_health_status(
    days_since_commit: Optional[int],
    days_since_release: int
) -> Tuple[str, str]:
    """
    Calculate health status based on activity

    Args:
        days_since_commit: Days since last GitHub commit (None if no GitHub)
        days_since_release: Days since last PyPI release

    Returns:
        Tuple of (status, recommendation)
    """
    # If we have GitHub data, prioritize it
    if days_since_commit is not None:
        if days_since_commit < 90:
            return "Active", "Active & Healthy"
        elif days_since_commit < 180:
            return "Slow", "Moderately Active"
        else:
            return "Zombie", "Low Activity - Consider Alternatives"

    # Fall back to PyPI release dates
    if days_since_release < 180:
        return "Active", "Active & Healthy"
    elif days_since_release < 365:
        return "Slow", "Moderately Active"
    else:
        return "Zombie", "Low Activity - Consider Alternatives"


def format_relative_date(date: datetime) -> str:
    """
    Format a date as relative time (e.g., '3 days ago')

    Args:
        date: Datetime to format

    Returns:
        Formatted string
    """
    delta = datetime.now(timezone.utc) - date
    days = delta.days

    if days == 0:
        return "today"
    elif days == 1:
        return "1 day ago"
    elif days < 30:
        return f"{days} days ago"
    elif days < 60:
        return "1 month ago"
    elif days < 365:
        months = days // 30
        return f"{months} months ago"
    else:
        years = days // 365
        if years == 1:
            return "1 year ago"
        return f"{years} years ago"
