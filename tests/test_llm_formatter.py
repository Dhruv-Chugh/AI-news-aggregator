"""Unit tests for LLM Markdown Formatter Service & Article.to_llm_markdown()."""

from datetime import datetime, timedelta, timezone
from typing import Generator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database.models import Article, Base, Source
from app.database.repository import NewsRepository
from app.services.llm_formatter import (
    LLMMarkdownFormatter,
    format_article_for_llm,
    format_articles_for_llm,
)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """In-memory SQLite database session for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


@pytest.fixture
def sample_sources(db_session: Session) -> dict[str, Source]:
    yt_src = Source(
        name="Think School",
        source_type="youtube",
        url="https://youtube.com/@thinkschool",
        channel_id="UCKZozRVHRYsYHGEyNKuhhdA",
        handle="@thinkschool",
    )
    oai_src = Source(
        name="OpenAI",
        source_type="openai",
        url="https://openai.com/news",
    )
    ant_src = Source(
        name="Anthropic",
        source_type="anthropic",
        url="https://anthropic.com/news",
    )
    db_session.add_all([yt_src, oai_src, ant_src])
    db_session.commit()
    return {"youtube": yt_src, "openai": oai_src, "anthropic": ant_src}


def test_article_to_llm_markdown_full_article(sample_sources):
    """Verify Article.to_llm_markdown() formats an article with full web content."""
    now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    art = Article(
        source_id=sample_sources["openai"].id,
        source=sample_sources["openai"],
        external_id="oai_test_1",
        title="OpenAI Alignment Breakthrough",
        url="https://openai.com/index/alignment-breakthrough",
        author="OpenAI Alignment Team",
        category="Research",
        published_at=now,
        summary="Summary of alignment breakthrough.",
        raw_content="### Introduction\nThis is the complete research paper content extracted from openai.com.",
        content_type="article",
        word_count=520,
        metadata_json={"categories": ["Research", "Safety"]},
    )

    md = art.to_llm_markdown(index=1)
    assert "## 1. [OpenAI] OpenAI Alignment Breakthrough" in md
    assert "- **Source**: OpenAI (`openai`)" in md
    assert "- **Original URL**: https://openai.com/index/alignment-breakthrough" in md
    assert "- **Published**: 2026-11-04 12:00 UTC" in md
    assert "- **Author / Channel**: OpenAI Alignment Team" in md
    assert "- **Category / Focus**: Research" in md
    assert "- **Content Type**: Full Web Article" in md
    assert "- **Word Count**: 520 words" in md
    assert "- **External ID**: `oai_test_1`" in md
    assert "- **Tags**: `Research`, `Safety`" in md
    assert "### Full Content:" in md
    assert "This is the complete research paper content extracted from openai.com." in md


def test_article_to_llm_markdown_spoken_transcript(sample_sources):
    """Verify Article.to_llm_markdown() formats a YouTube video transcript."""
    now = datetime(2026, 11, 4, 15, 30, 0, tzinfo=timezone.utc)
    art = Article(
        source_id=sample_sources["youtube"].id,
        source=sample_sources["youtube"],
        external_id="yt_vid_99",
        title="Geopolitics of Semiconductor Manufacturing",
        url="https://www.youtube.com/watch?v=yt_vid_99",
        author="Think School",
        category="YouTube",
        published_at=now,
        summary="Case study on chip war.",
        raw_content="[00:00:00] In this video, we analyze the semiconductor supply chain and Taiwan.",
        content_type="transcript",
        word_count=3500,
        metadata_json={"channel_id": "UCKZozRVHRYsYHGEyNKuhhdA", "transcript_language": "English"},
    )

    md = art.to_llm_markdown(index=2)
    assert "## 2. [Think School] Geopolitics of Semiconductor Manufacturing" in md
    assert "- **Source**: Think School (`youtube`)" in md
    assert "- **Content Type**: Spoken Transcript" in md
    assert "- **Word Count**: 3,500 words" in md
    assert "- **Language**: English" in md
    assert "### Spoken Transcript:" in md
    assert "[00:00:00] In this video, we analyze the semiconductor supply chain" in md


def test_article_to_llm_markdown_summary_fallback(sample_sources):
    """Verify Article.to_llm_markdown() falls back gracefully to summary when raw_content is missing."""
    now = datetime(2026, 11, 4, 10, 0, 0, tzinfo=timezone.utc)
    art = Article(
        source_id=sample_sources["anthropic"].id,
        source=sample_sources["anthropic"],
        external_id="ant_brief_1",
        title="Anthropic System Card Update",
        url="https://anthropic.com/news/system-card-update",
        author="Anthropic Safety",
        category="Safety",
        published_at=now,
        summary="Brief safety card announcement without long web body.",
        raw_content=None,
        content_type="article",
        word_count=45,
    )

    md = art.to_llm_markdown()
    assert "## [Anthropic] Anthropic System Card Update" in md
    assert "### Summary (Full Content Unavailable):" in md
    assert "> Brief safety card announcement without long web body." in md


def test_article_to_llm_markdown_empty_fallback():
    """Verify Article.to_llm_markdown() handles completely empty content/summary gracefully."""
    art = Article(
        external_id="empty_1",
        title="Empty Test",
        url="https://example.com/empty",
        published_at=datetime.now(timezone.utc),
        raw_content=None,
        summary=None,
    )
    md = art.to_llm_markdown()
    assert "### Content:" in md
    assert "_No content or summary available._" in md


def test_llm_formatter_format_articles(sample_sources):
    """Test LLMMarkdownFormatter.format_articles() overview header and delimiter."""
    now = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)
    art1 = Article(
        source_id=sample_sources["openai"].id,
        source=sample_sources["openai"],
        external_id="oai_1",
        title="OpenAI News",
        url="https://openai.com/1",
        published_at=now,
        raw_content="Content 1",
        word_count=100,
    )
    art2 = Article(
        source_id=sample_sources["anthropic"].id,
        source=sample_sources["anthropic"],
        external_id="ant_1",
        title="Anthropic Research",
        url="https://anthropic.com/1",
        published_at=now,
        raw_content="Content 2",
        word_count=200,
    )

    formatter = LLMMarkdownFormatter()
    doc = formatter.format_articles([art1, art2], title="Daily LLM Digest Feed")

    assert "# Daily LLM Digest Feed" in doc
    assert "**Total Items**: `2`" in doc
    assert "**Total Word Count**: `300`" in doc
    assert "OpenAI: 1" in doc
    assert "Anthropic: 1" in doc
    assert "## 1. [OpenAI] OpenAI News" in doc
    assert "## 2. [Anthropic] Anthropic Research" in doc
    assert "---" in doc


def test_llm_formatter_format_source_grouped(sample_sources):
    """Test LLMMarkdownFormatter.format_source_grouped() categorization by source type."""
    now = datetime.now(timezone.utc)
    art_yt = Article(
        source_id=sample_sources["youtube"].id,
        source=sample_sources["youtube"],
        external_id="yt_1",
        title="YT Video",
        url="https://yt.com/1",
        published_at=now,
        raw_content="Transcript",
        content_type="transcript",
    )
    art_oai = Article(
        source_id=sample_sources["openai"].id,
        source=sample_sources["openai"],
        external_id="oai_1",
        title="OAI Blog",
        url="https://openai.com/1",
        published_at=now,
        raw_content="Body",
        content_type="article",
    )

    formatter = LLMMarkdownFormatter()
    doc = formatter.format_source_grouped([art_yt, art_oai])

    assert "# 📦 OpenAI News & Research (1 items)" in doc
    assert "# 📦 YouTube Knowledge & Spoken Transcripts (1 items)" in doc
    assert "## 1. [OpenAI] OAI Blog" in doc
    assert "## 2. [Think School] YT Video" in doc


def test_llm_formatter_empty_articles():
    """Test formatting empty article list."""
    formatter = LLMMarkdownFormatter()
    doc = formatter.format_articles([])
    assert "_No articles found matching the specified criteria._" in doc


def test_repository_export_llm_markdown(db_session: Session, sample_sources):
    """Test repository-level export_llm_markdown() method."""
    repo = NewsRepository(session=db_session)
    now = datetime.now(timezone.utc)

    repo.articles.upsert(
        external_id="repo_art_1",
        title="Repository Test Article",
        url="https://test.com/repo-article",
        published_at=now,
        source_id=sample_sources["openai"].id,
        author="Tester",
        category="Testing",
        raw_content="This is stored inside the database repository.",
        content_type="article",
        word_count=25,
    )

    md = repo.export_llm_markdown()
    assert "# Scraped Articles & Knowledge Feed for LLM Digest" in md
    assert "Repository Test Article" in md
    assert "This is stored inside the database repository." in md

