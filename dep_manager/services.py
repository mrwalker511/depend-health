"""
API clients for PyPI and GitHub

This module provides async HTTP clients with connection pooling
for efficient API requests.
"""

import httpx
import re
import logging
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class APIClient:
    """
    Async API client for fetching package and repository information

    Uses connection pooling for better performance when making multiple requests.
    """

    PYPI_URL = "https://pypi.org/pypi/{package}/json"
    GITHUB_API_URL = "https://api.github.com/repos/{owner}/{repo}"

    # Connection limits for pooling
    DEFAULT_TIMEOUT = 30.0
    MAX_CONNECTIONS = 100
    MAX_KEEPALIVE_CONNECTIONS = 20

    def __init__(self):
        """Initialize the API client with connection pooling"""
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self):
        """Async context manager entry"""
        limits = httpx.Limits(
            max_connections=self.MAX_CONNECTIONS,
            max_keepalive_connections=self.MAX_KEEPALIVE_CONNECTIONS
        )
        self._client = httpx.AsyncClient(
            timeout=self.DEFAULT_TIMEOUT,
            limits=limits,
            follow_redirects=True
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit"""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def fetch_pypi_info(self, package_name: str) -> Dict[str, Any]:
        """
        Fetch package information from PyPI

        Args:
            package_name: Name of the package to fetch

        Returns:
            Dict containing PyPI package data

        Raises:
            httpx.HTTPStatusError: If package not found or API error
            ValueError: If client not initialized (use as context manager)
        """
        if not self._client:
            # Fallback: create temporary client if not used as context manager
            async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
                url = self.PYPI_URL.format(package=package_name)
                logger.debug(f"Fetching PyPI info for {package_name}")
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

        url = self.PYPI_URL.format(package=package_name)
        logger.debug(f"Fetching PyPI info for {package_name}")
        response = await self._client.get(url)
        response.raise_for_status()
        logger.info(f"Successfully fetched PyPI info for {package_name}")
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
            ValueError: If client not initialized (use as context manager)
        """
        if not self._client:
            # Fallback: create temporary client if not used as context manager
            async with httpx.AsyncClient(timeout=self.DEFAULT_TIMEOUT) as client:
                url = self.GITHUB_API_URL.format(owner=owner, repo=repo)
                logger.debug(f"Fetching GitHub info for {owner}/{repo}")
                response = await client.get(url)
                response.raise_for_status()
                return response.json()

        url = self.GITHUB_API_URL.format(owner=owner, repo=repo)
        logger.debug(f"Fetching GitHub info for {owner}/{repo}")
        response = await self._client.get(url)
        response.raise_for_status()
        logger.info(f"Successfully fetched GitHub info for {owner}/{repo}")
        return response.json()

    def extract_github_repo(self, pypi_data: Dict[str, Any]) -> Optional[tuple[str, str]]:
        """
        Extract GitHub owner and repo from PyPI data using multiple strategies

        Args:
            pypi_data: PyPI API response data

        Returns:
            Tuple of (owner, repo) or None if not found
        """
        # Check various places where GitHub URL might be
        urls_to_check = []

        # Project URLs (prioritize source/repository URLs)
        info = pypi_data.get("info", {})
        project_urls = info.get("project_urls") or {}

        # Prioritize certain keys that are more likely to have the repo
        priority_keys = ["Repository", "Source", "Source Code", "GitHub", "Code"]
        for key in priority_keys:
            if key in project_urls and project_urls[key]:
                urls_to_check.insert(0, project_urls[key])

        # Add remaining project URLs
        for key, url in project_urls.items():
            if url and key not in priority_keys:
                urls_to_check.append(url)

        # Home page and other fields
        for field in ["home_page", "project_url", "package_url", "download_url"]:
            url = info.get(field)
            if url:
                urls_to_check.append(url)

        # Try to find GitHub URL with multiple patterns
        github_patterns = [
            r'github\.com[:/]([^/\s]+)/([^/\s#?.]+)',  # Match both https:// and git@
            r'github\.com/([^/\s]+)/([^/\s]+)',         # Standard pattern
        ]

        for url in urls_to_check:
            if not url or not isinstance(url, str):
                continue

            for pattern in github_patterns:
                match = re.search(pattern, url, re.IGNORECASE)
                if match:
                    owner, repo = match.groups()
                    # Clean up repo name (remove .git, trailing slashes, fragments, etc.)
                    repo = repo.rstrip('/').replace('.git', '').split('#')[0].split('?')[0]
                    owner = owner.rstrip('/')

                    logger.info(f"Found GitHub repo: {owner}/{repo}")
                    return (owner, repo)

        logger.debug("No GitHub repository found in PyPI data")
        return None
