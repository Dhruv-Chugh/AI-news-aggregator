"""SQLAlchemy 2.0 ORM Models for AI News Aggregator.

Defines schemas for:
- Source: Monitored YouTube channels, OpenAI feeds, Anthropic feeds
- Article: Ingested articles and video transcripts with metadata & deduplication
- Digest: Synthesized daily markdown & HTML summaries
- Subscriber: Email recipients for the automated digest
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    mapped_column,
    relationship,
)


def utc_now() -> datetime:
    """Return timezone-aware current UTC datetime."""
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    """Base declarative class for all database models."""
    pass


class Source(Base):
    """Tracks content sources (YouTube channels, company RSS feeds, blogs)."""

    __tablename__ = "sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True
    )  # 'youtube', 'openai', 'anthropic', etc.
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    feed_url: Mapped[Optional[str]] = mapped_column(String(1024), nullable=True)
    channel_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    handle: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    last_scraped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    articles: Mapped[List["Article"]] = relationship(
        "Article", back_populates="source", cascade="all, delete-orphan"
    )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize source model to dictionary representation."""
        return {
            "id": self.id,
            "name": self.name,
            "source_type": self.source_type,
            "url": self.url,
            "feed_url": self.feed_url,
            "channel_id": self.channel_id,
            "handle": self.handle,
            "is_active": self.is_active,
            "last_scraped_at": self.last_scraped_at.isoformat() if self.last_scraped_at else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Source(id={self.id}, name='{self.name}', type='{self.source_type}', active={self.is_active})>"


class Article(Base):
    """Stores ingested articles, blog posts, and YouTube video transcripts."""

    __tablename__ = "articles"
    __table_args__ = (
        Index("ix_articles_pub_summarized", "published_at", "is_summarized"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("sources.id", ondelete="CASCADE"), nullable=True, index=True
    )
    external_id: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, nullable=False
    )  # YouTube video ID, OpenAI article slug, or Anthropic URL hash
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    url: Mapped[str] = mapped_column(String(1024), nullable=False)
    author: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    raw_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Full web content or transcript
    content_type: Mapped[str] = mapped_column(
        String(50), default="article", nullable=False
    )  # 'article', 'transcript', 'video'
    word_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    metadata_json: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON, nullable=True)
    is_summarized: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False
    )

    # Relationships
    source: Mapped[Optional["Source"]] = relationship("Source", back_populates="articles")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize article model to dictionary representation."""
        return {
            "id": self.id,
            "source_id": self.source_id,
            "external_id": self.external_id,
            "title": self.title,
            "url": self.url,
            "author": self.author,
            "category": self.category,
            "published_at": self.published_at.isoformat(),
            "summary": self.summary,
            "content_type": self.content_type,
            "word_count": self.word_count,
            "metadata": self.metadata_json or {},
            "is_summarized": self.is_summarized,
            "created_at": self.created_at.isoformat(),
        }

    def to_llm_markdown(self, index: Optional[int] = None) -> str:
        """Format article metadata and full content into simple, clean Markdown for LLMs."""
        source_name = self.source.name if self.source else (self.category or "Unknown Source")
        source_type = self.source.source_type if self.source else "article"
        prefix = f"{index}. " if index is not None else ""
        pub_str = (
            self.published_at.strftime("%Y-%m-%d %H:%M UTC")
            if self.published_at
            else "Unknown Date"
        )
        type_label = "Spoken Transcript" if self.content_type == "transcript" else "Full Web Article"
        word_count_str = f"{self.word_count:,} words" if self.word_count else "Not counted"

        lines = [
            f"## {prefix}[{source_name}] {self.title}",
            f"- **Source**: {source_name} (`{source_type}`)",
            f"- **Original URL**: {self.url}",
            f"- **Published**: {pub_str}",
            f"- **Author / Channel**: {self.author or 'Unknown'}",
            f"- **Category / Focus**: {self.category or 'General'}",
            f"- **Content Type**: {type_label}",
            f"- **Word Count**: {word_count_str}",
            f"- **External ID**: `{self.external_id}`",
        ]

        meta = self.metadata_json or {}
        if meta.get("transcript_language"):
            lines.append(f"- **Language**: {meta['transcript_language']}")
        if meta.get("categories") and isinstance(meta["categories"], list):
            cats_joined = ", ".join(f"`{c}`" for c in meta["categories"] if c)
            if cats_joined:
                lines.append(f"- **Tags**: {cats_joined}")

        lines.append("")

        if self.raw_content and self.raw_content.strip():
            header = "### Spoken Transcript:" if self.content_type == "transcript" else "### Full Content:"
            lines.append(header)
            lines.append(self.raw_content.strip())
        elif self.summary and self.summary.strip():
            lines.append("### Summary (Full Content Unavailable):")
            lines.append(f"> {self.summary.strip()}")
        else:
            lines.append("### Content:")
            lines.append("_No content or summary available._")

        return "\n".join(lines)

    def __repr__(self) -> str:
        safe_title = self.title[:30] if self.title else "Untitled"
        return f"<Article(id={self.id}, external_id='{self.external_id}', title='{safe_title}...')>"


class Digest(Base):
    """Synthesized daily news digest sent to subscribers."""

    __tablename__ = "digests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    digest_date: Mapped[date] = mapped_column(Date, index=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    content_html: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    article_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize digest model to dictionary representation."""
        return {
            "id": self.id,
            "digest_date": self.digest_date.isoformat(),
            "title": self.title,
            "article_count": self.article_count,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Digest(id={self.id}, date={self.digest_date}, title='{self.title}', count={self.article_count})>"


class Subscriber(Base):
    """Email recipient for synthesized daily news digests."""

    __tablename__ = "subscribers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize subscriber model to dictionary representation."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "is_active": self.is_active,
            "created_at": self.created_at.isoformat(),
        }

    def __repr__(self) -> str:
        return f"<Subscriber(id={self.id}, email='{self.email}', active={self.is_active})>"

