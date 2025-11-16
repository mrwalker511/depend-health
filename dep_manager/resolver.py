"""
Dependency resolution and conflict detection

This module provides utilities for parsing requirements files,
fetching package dependencies, and detecting version conflicts.
"""

import httpx
import logging
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Set
from packaging.requirements import Requirement, InvalidRequirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version, InvalidVersion

# Configure logging
logger = logging.getLogger(__name__)


def get_local_requirements(filepath: str) -> List[Requirement]:
    """
    Parse a requirements.txt file into Requirement objects

    Args:
        filepath: Path to requirements.txt file

    Returns:
        List of Requirement objects from the file
    """
    requirements = []

    if not Path(filepath).exists():
        return requirements

    with open(filepath, 'r', encoding='utf-8') as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            try:
                req = Requirement(line)
                requirements.append(req)
            except InvalidRequirement as e:
                logger.warning(
                    f"Skipping invalid requirement at line {line_num} in {filepath}: {line} ({e})"
                )
                continue

    logger.info(f"Parsed {len(requirements)} requirements from {filepath}")
    return requirements


async def get_package_dependencies(package_name: str) -> Tuple[str, List[str]]:
    """
    Fetch package dependencies from PyPI

    Args:
        package_name: Name of the package to fetch

    Returns:
        Tuple of (version, list of dependency strings from requires_dist)
    """
    url = f"https://pypi.org/pypi/{package_name}/json"

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(url)
        response.raise_for_status()
        data = response.json()

    version = data["info"]["version"]
    requires_dist = data["info"].get("requires_dist") or []

    return version, requires_dist


def parse_dependency(dep_string: str) -> Optional[Requirement]:
    """
    Parse a dependency string from requires_dist, filtering out optional dependencies

    Args:
        dep_string: Dependency string (e.g., "requests>=2.0.0; extra == 'dev'")

    Returns:
        Requirement object or None if it should be skipped (optional dependencies,
        environment-specific, or invalid)
    """
    try:
        req = Requirement(dep_string)

        # Skip dependencies with extra markers (optional dependencies like [dev], [test])
        if req.marker and 'extra' in str(req.marker):
            logger.debug(f"Skipping optional dependency: {dep_string}")
            return None

        # Skip platform-specific dependencies for now (they may not apply)
        # We could enhance this to check current platform
        if req.marker and any(marker in str(req.marker) for marker in ['platform_system', 'sys_platform']):
            logger.debug(f"Skipping platform-specific dependency: {dep_string}")
            return None

        return req
    except InvalidRequirement as e:
        logger.warning(f"Failed to parse dependency '{dep_string}': {e}")
        return None


def check_specifier_conflict(spec1: SpecifierSet, spec2: SpecifierSet, package_name: str) -> Optional[str]:
    """
    Check if two version specifiers are incompatible using improved algorithm

    Args:
        spec1: First specifier set
        spec2: Second specifier set
        package_name: Name of the package being checked

    Returns:
        Conflict description string or None if no conflict
    """
    # If either is empty, no conflict (unconstrained)
    if not spec1 or not spec2:
        return None

    # Try to combine specifiers - if they can't be combined, there's a conflict
    # Test with a comprehensive range of versions including edge cases
    test_versions = _generate_test_versions(spec1, spec2)

    for ver_str in test_versions:
        try:
            ver = Version(ver_str)
            if ver in spec1 and ver in spec2:
                # Found a compatible version
                logger.debug(f"Found compatible version {ver} for {package_name}")
                return None
        except InvalidVersion:
            continue

    # No compatible version found
    logger.warning(f"Conflict detected for {package_name}: {spec1} vs {spec2}")
    return f"{package_name}: requires {spec1} vs {spec2}"


def _generate_test_versions(spec1: SpecifierSet, spec2: SpecifierSet) -> List[str]:
    """
    Generate a comprehensive list of versions to test for compatibility

    Args:
        spec1: First specifier set
        spec2: Second specifier set

    Returns:
        List of version strings to test
    """
    # Extract version numbers from specifiers
    versions: Set[str] = set()

    for spec in list(spec1) + list(spec2):
        # Extract version from specifier (e.g., ">=2.0.0" -> "2.0.0")
        version_str = str(spec).lstrip('><=!~')
        if version_str:
            versions.add(version_str)

    # Add common test versions
    common_versions = [
        "0.1.0", "0.5.0", "1.0.0", "1.5.0", "2.0.0", "2.5.0",
        "3.0.0", "4.0.0", "5.0.0", "10.0.0", "20.0.0", "50.0.0", "100.0.0"
    ]
    versions.update(common_versions)

    return sorted(list(versions), key=lambda v: Version(v) if _is_valid_version(v) else Version("0.0.0"))


def _is_valid_version(version_str: str) -> bool:
    """Check if a string is a valid version"""
    try:
        Version(version_str)
        return True
    except InvalidVersion:
        return False


def find_conflicts(
    new_package_name: str,
    new_package_version: str,
    new_dependencies: List[str],
    local_requirements: List[Requirement]
) -> List[str]:
    """
    Find conflicts between new package dependencies and local requirements

    Args:
        new_package_name: Name of the package being added
        new_package_version: Version of the new package
        new_dependencies: List of dependency strings from requires_dist
        local_requirements: List of local Requirement objects

    Returns:
        List of human-readable conflict descriptions
    """
    conflicts = []

    # Create a map of local requirements by package name
    local_map: Dict[str, Requirement] = {}
    for req in local_requirements:
        # Normalize package name (lowercase, replace - with _)
        normalized_name = req.name.lower().replace('-', '_')
        local_map[normalized_name] = req

    # Check if the new package itself conflicts with an existing requirement
    normalized_new_name = new_package_name.lower().replace('-', '_')
    if normalized_new_name in local_map:
        existing_req = local_map[normalized_new_name]
        if existing_req.specifier:
            try:
                ver = Version(new_package_version)
                if ver not in existing_req.specifier:
                    conflicts.append(
                        f"⚠️  Package '{new_package_name}' version {new_package_version} "
                        f"conflicts with existing requirement: {existing_req}"
                    )
                    logger.info(f"Version conflict: {new_package_name}=={new_package_version} vs {existing_req}")
            except InvalidVersion as e:
                logger.error(f"Invalid version '{new_package_version}': {e}")
                pass

    # Parse new package dependencies
    new_deps_parsed = []
    for dep_str in new_dependencies:
        req = parse_dependency(dep_str)
        if req:
            new_deps_parsed.append(req)

    # Check each new dependency against local requirements
    for new_dep in new_deps_parsed:
        normalized_dep_name = new_dep.name.lower().replace('-', '_')

        if normalized_dep_name in local_map:
            local_req = local_map[normalized_dep_name]

            # Check if specifiers conflict
            conflict_msg = check_specifier_conflict(
                new_dep.specifier,
                local_req.specifier,
                new_dep.name
            )

            if conflict_msg:
                conflicts.append(
                    f"⚠️  '{new_package_name}' requires '{new_dep}' "
                    f"but you have '{local_req}' installed"
                )

    return conflicts


def append_to_requirements(filepath: str, package_name: str, version: Optional[str] = None) -> bool:
    """
    Append a package to requirements.txt, avoiding duplicates

    Args:
        filepath: Path to requirements.txt
        package_name: Name of package to add
        version: Optional version specifier

    Returns:
        True if package was added, False if it already existed
    """
    # Check if package already exists in requirements
    existing_reqs = get_local_requirements(filepath)
    normalized_name = package_name.lower().replace('-', '_')

    for req in existing_reqs:
        if req.name.lower().replace('-', '_') == normalized_name:
            logger.warning(f"Package '{package_name}' already exists in {filepath}")
            return False

    # Append the new requirement
    with open(filepath, 'a', encoding='utf-8') as f:
        if version:
            f.write(f"\n{package_name}=={version}\n")
            logger.info(f"Added {package_name}=={version} to {filepath}")
        else:
            f.write(f"\n{package_name}\n")
            logger.info(f"Added {package_name} to {filepath}")

    return True
