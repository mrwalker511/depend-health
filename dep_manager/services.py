"""
API clients for PyPI and GitHub
"""

import httpx
import re
from typing import Optional, Dict, Any
from datetime import datetime


class APIClient:
    """Async API client for fetching package and repository information"""

    PYPI_URL = "https://pypi.org/pypi/{package}/json"
    GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}"

    async def fetch_pypi_info(self, package_name: str) -> Dict[str, Any]:
        """
        Fetch package information from PyPI

        Args:
            package_name: Name of the package to fetch

        Returns:
            Dict containing PyPI package data

        Raises:
            httpx.HTTPStatusError: If package not found or API error
        """
        url = self.PYPI_URL.format(package=package_name)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    async def fetch_github_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Fetch repository information from GitHub API

        Args:
            owner: GitHub repository owner
            repo: Repository name

        Returns:
            Dict containing GitHub repository data

        Raises:
            httpx.HTTPStatusError: If repository not found or API error
        """
        url = self.GITHUB_API_URL.format(owner=owner, repo=repo)

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()

    def extract_github_repo(self, pypi_data: Dict[str, Any]) -> Optional[tuple[str, str]]:
        """
        Extract GitHub owner and repo from PyPI data

        Args:
            pypi_data: PyPI API response data

        Returns:
            Tuple of (owner, repo) or None if not found
        """
        # Check various places where GitHub URL might be
        urls_to_check = []

        # Project URLs
        info = pypi_data.get("info", {})
        project_urls = info.get("project_urls") or {}

        for key, url in project_urls.items():
            if url:
                urls_to_check.append(url)

        # Home page and other fields
        for field in ["home_page", "project_url", "package_url"]:
            url = info.get(field)
            if url:
                urls_to_check.append(url)

        # Try to find GitHub URL
        github_pattern = r'github\.com/([^/]+)/([^/\s]+)'

        for url in urls_to_check:
            match = re.search(github_pattern, url)
            if match:
                owner, repo = match.groups()
                # Clean up repo name (remove .git, trailing slashes, etc.)
                repo = repo.rstrip('/').replace('.git', '')
                return (owner, repo)

        return None
