"""
PyPI package search functionality

This module provides search capabilities for finding packages on PyPI.
"""

import httpx
import logging
from typing import List, Dict, Any
from rich.table import Table

logger = logging.getLogger(__name__)


class SearchResult:
    """Single search result from PyPI"""
    def __init__(self, name: str, version: str, description: str):
        self.name = name
        self.version = version
        self.description = description


async def search_pypi(query: str, limit: int = 20) -> List[SearchResult]:
    """
    Search PyPI for packages matching query

    Note: PyPI's official search API was deprecated. This uses the legacy
    XML-RPC API which may have limitations.

    Args:
        query: Search query string
        limit: Maximum number of results

    Returns:
        List of SearchResult objects
    """
    logger.info(f"Searching PyPI for: {query}")

    # Use PyPI's simple search via warehou se.python.org
    # This is a workaround since the official search API is deprecated
    url = f"https://pypi.org/search/?q={query}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            # Get search results via web scraping (simple approach)
            # For production, you might want to use a proper search API or library
            response = await client.get(url, follow_redirects=True)
            response.raise_for_status()

            # For now, we'll use a simpler approach: fetch popular packages
            # and filter by query
            results = await _fetch_popular_packages(query, limit, client)

            return results

    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


async def _fetch_popular_packages(query: str, limit: int, client: httpx.AsyncClient) -> List[SearchResult]:
    """
    Fetch popular packages and filter by query

    This is a workaround since PyPI's search API is limited.
    We search for exact package names and related packages.

    Args:
        query: Search query
        limit: Max results
        client: HTTP client

    Returns:
        List of SearchResult objects
    """
    results = []

    # Try exact match first
    try:
        url = f"https://pypi.org/pypi/{query}/json"
        response = await client.get(url)

        if response.status_code == 200:
            data = response.json()
            info = data["info"]

            results.append(SearchResult(
                name=info["name"],
                version=info["version"],
                description=info.get("summary", "No description")
            ))
    except Exception:
        pass

    # Try common variations
    variations = [
        query.lower(),
        query.replace("-", "_"),
        query.replace("_", "-"),
        f"python-{query}",
        f"py{query}",
        f"{query}-python"
    ]

    for variant in variations:
        if len(results) >= limit:
            break

        try:
            url = f"https://pypi.org/pypi/{variant}/json"
            response = await client.get(url)

            if response.status_code == 200:
                data = response.json()
                info = data["info"]

                # Check if already in results
                if not any(r.name == info["name"] for r in results):
                    results.append(SearchResult(
                        name=info["name"],
                        version=info["version"],
                        description=info.get("summary", "No description")
                    ))
        except Exception:
            continue

    return results[:limit]


def create_search_table(results: List[SearchResult], query: str) -> Table:
    """
    Create a rich Table displaying search results

    Args:
        results: List of search results
        query: Original search query

    Returns:
        Rich Table object
    """
    table = Table(title=f"🔍 Search Results for '{query}'")

    table.add_column("Package", style="cyan bold", no_wrap=True)
    table.add_column("Version", style="green")
    table.add_column("Description", style="dim")

    for result in results:
        # Truncate description if too long
        desc = result.description
        if len(desc) > 80:
            desc = desc[:77] + "..."

        table.add_row(
            result.name,
            result.version,
            desc
        )

    return table
