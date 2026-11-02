"""Pydantic data models for OpenAI news, research, and engineering articles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class OpenAICategory(str, Enum):
    """Enumeration of recognized OpenAI article categories."""

    RESEARCH = "Research"
    ENGINEERING = "Engineering"
    PRODUCT = "Product"
    SAFETY = "Safety"
    SECURITY = "Security"
    COMPANY = "Company"
    AI_ADOPTION = "AI Adoption"
    INTELLIGENCE_AGE = "Intelligence Age"
    GLOBAL_AFFAIRS = "Global Affairs"
    OTHER = "Other"

    @classmethod
    def from_string(cls, val: str) -> str:
        """Normalize string to matching category or title-cased string."""
        for member in cls:
            if member.value.lower() == val.strip().lower():
                return member.value
        return val.strip().title()


class OpenAIArticle(BaseModel):
    """Pydantic model representing an article published by OpenAI."""

    article_id: str = Field(..., description="Unique ID or GUID from the RSS feed")
    title: str = Field(..., description="Title of the article")
    url: str = Field(..., description="Direct link to the article on openai.com")
    published_at: datetime = Field(..., description="Publication timestamp in UTC")
    summary: str = Field(default="", description="Summary or excerpt from OpenAI RSS")
    content: Optional[str] = Field(default=None, description="Full article text or markdown extracted from original website")
    word_count: Optional[int] = Field(default=None, description="Word count of full article body")
    categories: List[str] = Field(default_factory=list, description="Categories or tags assigned to the article")
    author: Optional[str] = Field(default="OpenAI", description="Author or publishing entity")

    @field_validator("published_at", mode="before")
    @classmethod
    def ensure_utc_timezone(cls, v: Any) -> datetime:
        """Ensure published_at is a timezone-aware UTC datetime."""
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v

    @property
    def has_full_content(self) -> bool:
        """Check whether full article content has been extracted."""
        return bool(self.content and len(self.content.strip()) > 0)

    @property
    def is_research(self) -> bool:
        """Check whether this article belongs to OpenAI Research."""
        return any(c.lower() == "research" for c in self.categories) or "/research/" in self.url

    @property
    def is_engineering(self) -> bool:
        """Check whether this article belongs to OpenAI Engineering."""
        return any(c.lower() == "engineering" for c in self.categories) or "/engineering/" in self.url

    @property
    def primary_category(self) -> str:
        """Get the primary category name or fallback to 'General'."""
        return self.categories[0] if self.categories else "General"

    def matches_category(self, target_category: str) -> bool:
        """Case-insensitive check if article matches a target category."""
        target = target_category.strip().lower()
        if target in ("all", "*"):
            return True
        return any(c.lower() == target for c in self.categories)

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return self.model_dump()

    def to_markdown(self) -> str:
        """Export article as formatted GitHub-Flavored Markdown."""
        pub_str = self.published_at.strftime("%Y-%m-%d %H:%M UTC")
        cats_str = ", ".join(f"`{c}`" for c in self.categories) if self.categories else "`General`"
        lines = [
            f"### [{self.title}]({self.url})",
            f"- **Categories:** {cats_str}",
            f"- **Published:** {pub_str}",
            f"- **Author:** {self.author}",
            f"- **Original Source:** [{self.url}]({self.url})",
            "",
        ]

        if self.has_full_content and self.content:
            w_count = self.word_count or len(self.content.split())
            lines.extend([
                f"#### Full Article Content ({w_count:,} words)",
                "",
                self.content,
                "",
            ])
        else:
            lines.extend([
                "#### Summary",
                f"> {self.summary}" if self.summary else "> _No summary provided._",
                "",
            ])

        return "\n".join(lines).strip()


class OpenAIFilterCriteria(BaseModel):
    """Pydantic criteria for filtering OpenAI articles by timeframe and category."""

    hours_back: Optional[int] = Field(
        default=24,
        description="Number of hours to look back (e.g. 24 for daily digest). Set None for all.",
    )
    since: Optional[datetime] = Field(
        default=None,
        description="Explicit start cutoff datetime in UTC. Overrides hours_back if provided.",
    )
    categories: Optional[List[str]] = Field(
        default=None,
        description="List of categories to include, e.g. ['Research', 'Engineering']. None includes all.",
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Optional case-insensitive text search in title or summary.",
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of articles to return (None for unlimited).",
    )

    @property
    def cutoff_datetime(self) -> Optional[datetime]:
        """Calculate the active cutoff UTC datetime."""
        if self.since is not None:
            return self.since if self.since.tzinfo else self.since.replace(tzinfo=timezone.utc)
        if self.hours_back is not None and self.hours_back > 0:
            return datetime.now(timezone.utc) - timedelta(hours=self.hours_back)
        return None

