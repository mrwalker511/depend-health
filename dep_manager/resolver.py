"""
Dependency resolution and conflict detection
"""

import httpx
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version


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

    with open(filepath, 'r') as f:
        for line in f:
            line = line.strip()

            # Skip empty lines and comments
            if not line or line.startswith('#'):
                continue

            try:
                req = Requirement(line)
                requirements.append(req)
            except Exception:
                # Skip invalid lines
                continue

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
    Parse a dependency string from requires_dist

    Args:
        dep_string: Dependency string (e.g., "requests>=2.0.0; extra == 'dev'")

    Returns:
        Requirement object or None if it has environment markers we should skip
    """
    try:
        req = Requirement(dep_string)

        # Skip dependencies with extra markers (optional dependencies)
        if req.marker and 'extra' in str(req.marker):
            return None

        return req
    except Exception:
        return None


def check_specifier_conflict(spec1: SpecifierSet, spec2: SpecifierSet, package_name: str) -> Optional[str]:
    """
    Check if two version specifiers are incompatible

    Args:
        spec1: First specifier set
        spec2: Second specifier set
        package_name: Name of the package being checked

    Returns:
        Conflict description string or None if no conflict
    """
    # If either is empty, no conflict
    if not spec1 or not spec2:
        return None

    # Try to find a version that satisfies both specifiers
    # We'll test a range of common versions
    test_versions = [
        "0.1.0", "0.5.0", "1.0.0", "1.5.0", "2.0.0", "3.0.0",
        "5.0.0", "10.0.0", "20.0.0", "50.0.0", "100.0.0"
    ]

    for ver_str in test_versions:
        try:
            ver = Version(ver_str)
            if ver in spec1 and ver in spec2:
                # Found a compatible version
                return None
        except Exception:
            continue

    # No compatible version found
    return f"{package_name}: requires {spec1} vs {spec2}"


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
            except Exception:
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


def append_to_requirements(filepath: str, package_name: str, version: Optional[str] = None):
    """
    Append a package to requirements.txt

    Args:
        filepath: Path to requirements.txt
        package_name: Name of package to add
        version: Optional version specifier
    """
    with open(filepath, 'a') as f:
        if version:
            f.write(f"\n{package_name}=={version}\n")
        else:
            f.write(f"\n{package_name}\n")
