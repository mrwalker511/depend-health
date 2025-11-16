"""
Data models for API responses and health reports
"""

from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal, Dict
from datetime import datetime


class PyPIInfo(BaseModel):
    """Model for PyPI package information"""
    name: str = Field(..., description="Package name")
    version: str = Field(..., description="Latest version")
    summary: str = Field(..., description="Package description")
    license: Optional[str] = Field(None, description="License type")
    release_date: datetime = Field(..., description="Release date of latest version")
    project_urls: Optional[Dict[str, str]] = Field(None, description="Project URLs")

    @field_validator('summary')
    @classmethod
    def truncate_summary(cls, v: str) -> str:
        """Truncate very long summaries to prevent display issues"""
        max_length = 500
        if len(v) > max_length:
            return v[:max_length] + "..."
        return v


class GitHubInfo(BaseModel):
    """Model for GitHub repository information"""
    repo_name: str = Field(..., description="GitHub repository owner/name")
    pushed_at: datetime = Field(..., description="Last commit timestamp")
    open_issues: int = Field(..., ge=0, description="Number of open issues")
    stars: int = Field(..., ge=0, description="Number of stars")


class HealthReport(BaseModel):
    """Complete health report for a package"""
    pypi: PyPIInfo = Field(..., description="PyPI package information")
    github: Optional[GitHubInfo] = Field(None, description="GitHub repository information")
    health_status: Literal["Active", "Slow", "Zombie"] = Field(..., description="Health status")
    recommendation: str = Field(..., description="Recommendation text")
    days_since_commit: Optional[int] = Field(None, ge=0, description="Days since last commit")
    days_since_release: int = Field(..., ge=0, description="Days since last release")
