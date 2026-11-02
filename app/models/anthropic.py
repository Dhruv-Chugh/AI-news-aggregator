"""Pydantic data models for Anthropic news, research, and engineering articles."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator


class AnthropicCategory(str, Enum):
    """Enumeration of recognized Anthropic article categories."""

    NEWS = "News"
    ENGINEERING = "Engineering"
    RESEARCH = "Research"
    ANNOUNCEMENTS = "Announcements"
    SAFETY = "Safety"
    PRODUCT = "Product"
    OTHER = "Other"

    @classmethod
    def from_string(cls, val: str) -> str:
        """Normalize string to matching category or title-cased string."""
        cleaned = val.strip().lower()
        for member in cls:
            if member.value.lower() == cleaned:
                return member.value
        return val.strip().title()


class AnthropicArticle(BaseModel):
    """Pydantic model representing an article published by Anthropic."""

    article_id: str = Field(..., description="Unique ID, GUID, or canonical URL from the RSS feed")
    title: str = Field(..., description="Title of the article")
    url: str = Field(..., description="Direct link to the article on anthropic.com")
    published_at: datetime = Field(..., description="Publication timestamp in UTC")
    summary: str = Field(default="", description="Summary or excerpt from Anthropic RSS")
    content: Optional[str] = Field(default=None, description="Full article text or markdown extracted from original website")
    word_count: Optional[int] = Field(default=None, description="Word count of full article body")
    categories: List[str] = Field(default_factory=list, description="Categories or tags assigned to the article")
    author: Optional[str] = Field(default="Anthropic", description="Author or publishing entity")
    feed_source: Optional[str] = Field(default=None, description="Identifier of the origin feed (e.g. 'news', 'engineering', 'research')")

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
        """Check whether this article belongs to Anthropic Research."""
        return any(c.lower() == "research" for c in self.categories) or "/research/" in self.url

    @property
    def is_engineering(self) -> bool:
        """Check whether this article belongs to Anthropic Engineering."""
        return any(c.lower() == "engineering" for c in self.categories) or "/engineering/" in self.url

    @property
    def is_news(self) -> bool:
        """Check whether this article belongs to Anthropic News / Announcements."""
        return (
            any(c.lower() in ("news", "announcements") for c in self.categories)
            or "/news/" in self.url
        )

    @property
    def primary_category(self) -> str:
        """Get the primary category name prioritizing Research > Engineering > News."""
        if self.is_research:
            return "Research"
        if self.is_engineering:
            return "Engineering"
        if self.is_news:
            return "News"
        return self.categories[0] if self.categories else "General"

    def matches_category(self, target_category: str) -> bool:
        """Case-insensitive check if article matches a target category."""
        target = target_category.strip().lower()
        if target in ("all", "*"):
            return True
        if target == "research" and self.is_research:
            return True
        if target == "engineering" and self.is_engineering:
            return True
        if target in ("news", "announcements") and self.is_news:
            return True
        return any(c.lower() == target for c in self.categories)

    def to_dict(self) -> Dict[str, Any]:
        """Convert model to dictionary."""
        return self.model_dump()

    def to_markdown(self) -> str:
        """Export article as formatted GitHub-Flavored Markdown."""
        pub_str = self.published_at.strftime("%Y-%m-%d %H:%M UTC")
        cats_str = ", ".join(f"`{c}`" for c in self.categories) if self.categories else f"`{self.primary_category}`"
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


class AnthropicFilterCriteria(BaseModel):
    """Pydantic criteria for filtering Anthropic articles by timeframe and category."""

    hours_back: Optional[int] = Field(
        default=24,
        description="Filter articles published in the last N hours. None or 0 includes all.",
    )
    categories: List[str] = Field(
        default_factory=list,
        description="Target categories (e.g. ['Research', 'Engineering']). Empty matches all.",
    )
    search_query: Optional[str] = Field(
        default=None,
        description="Optional case-insensitive keyword to filter title or summary.",
    )
    limit: Optional[int] = Field(
        default=None,
        description="Maximum number of articles to return.",
    )

    @property
    def cutoff_time(self) -> Optional[datetime]:
        """Calculate the UTC datetime cutoff based on hours_back."""
        if self.hours_back and self.hours_back > 0:
            return datetime.now(timezone.utc) - timedelta(hours=self.hours_back)
        return None

    def is_within_timeframe(self, article: AnthropicArticle) -> bool:
        """Check if article published_at satisfies the hours_back cutoff."""
        cutoff = self.cutoff_time
        if cutoff is None:
            return True
        return article.published_at >= cutoff

    def matches(self, article: AnthropicArticle) -> bool:
        """Evaluate if an article satisfies all filter criteria."""
        if not self.is_within_timeframe(article):
            return False

        if self.categories:
            matches_any_cat = any(article.matches_category(cat) for cat in self.categories)
            if not matches_any_cat:
                return False

        if self.search_query:
            query = self.search_query.strip().lower()
            in_title = query in article.title.lower()
            in_summary = query in article.summary.lower()
            if not (in_title or in_summary):
                return False

        return True

