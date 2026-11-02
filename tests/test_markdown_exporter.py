"""Unit tests for Markdown Exporter Service and to_markdown() model methods."""

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.models.anthropic import AnthropicArticle
from app.models.openai import OpenAIArticle
from app.models.youtube import (
    TranscriptSnippet,
    VideoTranscript,
    YouTubeVideo,
)
from app.services.markdown_exporter import MarkdownExporter


@pytest.fixture
def sample_article():
    now = datetime(2026, 10, 30, 14, 0, 0, tzinfo=timezone.utc)
    return OpenAIArticle(
        article_id="test_art_1",
        title="Scaling Frontier Models Safely",
        url="https://openai.com/index/scaling-frontier-models-safely",
        published_at=now,
        summary="A breakthrough paper on multi-agent alignment verification.",
        categories=["Research", "Safety"],
        author="OpenAI Alignment Team",
    )


@pytest.fixture
def sample_anthropic_article():
    now = datetime(2026, 10, 28, 11, 0, 0, tzinfo=timezone.utc)
    return AnthropicArticle(
        article_id="https://www.anthropic.com/research/early-progress-drug-development",
        title="Early progress on accelerating drug development with Claude",
        url="https://www.anthropic.com/research/early-progress-drug-development",
        published_at=now,
        summary="Effort to speed up drug development with Claude.",
        categories=["Research"],
        author="Anthropic",
        feed_source="research",
    )


@pytest.fixture
def sample_video():
    now = datetime(2026, 10, 30, 15, 0, 0, tzinfo=timezone.utc)
    transcript = VideoTranscript(
        video_id="DHzC4VVmolk",
        available=True,
        text="Healthcare spending in America has reached 4.5 trillion dollars annually.",
        word_count=10,
        language="English",
        snippets=[TranscriptSnippet(start=0.0, duration=2.5, text="Healthcare spending in America...")],
    )
    return YouTubeVideo(
        video_id="DHzC4VVmolk",
        title="Why America's healthcare is Broken?",
        url="https://www.youtube.com/watch?v=DHzC4VVmolk",
        channel_id="UCKZozRVHRYsYHGEyNKuhhdA",
        channel_name="Think School",
        published_at=now,
        description="A detailed analysis of US healthcare economics.",
        transcript=transcript,
    )


def test_openai_article_to_markdown(sample_article):
    """Test model-level to_markdown() for OpenAIArticle."""
    md = sample_article.to_markdown()
    assert "### [Scaling Frontier Models Safely](https://openai.com/index/scaling-frontier-models-safely)" in md
    assert "- **Categories:** `Research`, `Safety`" in md
    assert "- **Published:** 2026-10-30 14:00 UTC" in md
    assert "- **Author:** OpenAI Alignment Team" in md
    assert "#### Summary" in md
    assert "> A breakthrough paper on multi-agent alignment verification." in md


def test_anthropic_article_to_markdown(sample_anthropic_article):
    """Test model-level to_markdown() for AnthropicArticle."""
    md = sample_anthropic_article.to_markdown()
    assert "### [Early progress on accelerating drug development with Claude](https://www.anthropic.com/research/early-progress-drug-development)" in md
    assert "- **Categories:** `Research`" in md
    assert "- **Published:** 2026-10-28 11:00 UTC" in md
    assert "- **Author:** Anthropic" in md
    assert "#### Summary" in md
    assert "> Effort to speed up drug development with Claude." in md


def test_youtube_video_to_markdown(sample_video):
    """Test model-level to_markdown() for YouTubeVideo."""
    md = sample_video.to_markdown()
    assert "### [Why America's healthcare is Broken?](https://www.youtube.com/watch?v=DHzC4VVmolk)" in md
    assert "- **Channel:** Think School (`UCKZozRVHRYsYHGEyNKuhhdA`)" in md
    assert "- **Format:** `Full Video`" in md
    assert "#### Description" in md
    assert "#### Transcript Knowledge (10 words, English)" in md


def test_markdown_exporter_openai_articles(sample_article):
    """Test MarkdownExporter document generation for OpenAI articles."""
    exporter = MarkdownExporter()
    doc = exporter.export_openai_articles([sample_article], title="Daily AI Briefing")

    assert "# Daily AI Briefing" in doc
    assert "🔬 Research Focus" in doc
    assert "[Scaling Frontier Models Safely]" in doc
    assert "Total Articles:" in doc


def test_markdown_exporter_anthropic_articles(sample_anthropic_article):
    """Test MarkdownExporter document generation for Anthropic articles."""
    exporter = MarkdownExporter()
    doc = exporter.export_anthropic_articles([sample_anthropic_article], title="Anthropic Briefing")

    assert "# Anthropic Briefing" in doc
    assert "🔬 Research Focus" in doc
    assert "[Early progress on accelerating drug development with Claude]" in doc
    assert "Total Articles:" in doc


def test_markdown_exporter_youtube_videos(sample_video):
    """Test MarkdownExporter document generation for YouTube videos."""
    exporter = MarkdownExporter()
    doc = exporter.export_youtube_videos([sample_video], title="Creator Roundup")

    assert "# Creator Roundup" in doc
    assert "Think School" in doc
    assert "[Why America's healthcare is Broken?]" in doc


def test_markdown_exporter_unified_digest(sample_article, sample_anthropic_article, sample_video):
    """Test unified multi-source digest markdown output."""
    exporter = MarkdownExporter()
    doc = exporter.export_unified_digest(
        openai_articles=[sample_article],
        anthropic_articles=[sample_anthropic_article],
        videos=[sample_video],
        title="Complete Daily Digest",
    )

    assert "# Complete Daily Digest" in doc
    assert "## 🔮 Anthropic News, Research & Engineering" in doc
    assert "## 📰 OpenAI News, Research & Engineering" in doc
    assert "## 🎥 YouTube Videos & Insights" in doc
    assert "Early progress on accelerating drug development with Claude" in doc
    assert "Scaling Frontier Models Safely" in doc
    assert "Why America's healthcare is Broken?" in doc


def test_markdown_exporter_save_to_file(tmp_path, sample_article):
    """Test saving markdown document to filesystem."""
    exporter = MarkdownExporter(default_output_dir=tmp_path)
    doc = exporter.export_openai_articles([sample_article])
    target_file = tmp_path / "subfolder" / "digest.md"

    saved_path = exporter.save_to_file(doc, target_file)
    assert saved_path.exists()
    content = saved_path.read_text(encoding="utf-8")
    assert "# OpenAI News & Research Digest" in content
    assert "Scaling Frontier Models Safely" in content
