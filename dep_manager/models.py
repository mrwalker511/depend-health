"""
Data models for API responses and health reports
"""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class PyPIInfo(BaseModel):
    """Model for PyPI package information"""
    name: str
    version: str
    summary: str
    license: Optional[str] = None
    release_date: datetime
    project_urls: Optional[dict] = None


class GitHubInfo(BaseModel):
    """Model for GitHub repository information"""
    repo_name: str
    pushed_at: datetime
    open_issues: int
    stars: int


class HealthReport(BaseModel):
    """Complete health report for a package"""
    pypi: PyPIInfo
    github: Optional[GitHubInfo] = None
    health_status: str
    recommendation: str
    days_since_commit: Optional[int] = None
    days_since_release: int
