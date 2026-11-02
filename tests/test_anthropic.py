"""Unit tests for Anthropic Scraper Service, Feed Parser, and Pydantic models."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.anthropic import (
    AnthropicArticle,
    AnthropicCategory,
    AnthropicFilterCriteria,
)
from app.scrapers.anthropic import (
    AnthropicArticleFilter,
    AnthropicFeedParser,
    AnthropicScraperService,
)


@pytest.fixture
def sample_articles():
    now = datetime.now(timezone.utc)
    return [
        AnthropicArticle(
            article_id="https://www.anthropic.com/research/early-progress-drug-development",
            title="Early progress on accelerating drug development with Claude",
            url="https://www.anthropic.com/research/early-progress-drug-development",
            published_at=now - timedelta(hours=3),
            summary="We're at the start of a major effort to speed up drug development with Claude.",
            categories=["Research"],
            author="Anthropic",
            feed_source="research",
        ),
        AnthropicArticle(
            article_id="https://www.anthropic.com/engineering/redesigning-source-control",
            title="Redesigning source control at Anthropic",
            url="https://www.anthropic.com/engineering/redesigning-source-control",
            published_at=now - timedelta(hours=10),
            summary="Source control became our biggest development bottleneck.",
            categories=["Engineering"],
            author="Anthropic",
            feed_source="engineering",
        ),
        AnthropicArticle(
            article_id="https://www.anthropic.com/news/expanding-partnership-aws",
            title="Expanding our partnership with AWS",
            url="https://www.anthropic.com/news/expanding-partnership-aws",
            published_at=now - timedelta(hours=30),  # Older than 24h
            summary="Strategic partnership update with Amazon Web Services.",
            categories=["News"],
            author="Anthropic",
            feed_source="news",
        ),
        AnthropicArticle(
            article_id="https://www.anthropic.com/research/older-alignment",
            title="Older Alignment Assessment Paper",
            url="https://www.anthropic.com/research/older-alignment",
            published_at=now - timedelta(days=7),
            summary="A deep evaluation of frontier model safety guarantees.",
            categories=["Research", "Safety"],
            author="Anthropic",
            feed_source="research",
        ),
    ]


# ---------------------------------------------------------------------------
# Pydantic Model Tests
# ---------------------------------------------------------------------------
def test_anthropic_article_properties():
    """Verify AnthropicArticle properties and category detection."""
    now = datetime.now(timezone.utc)
    res_article = AnthropicArticle(
        article_id="1",
        title="Claude Drug Discovery",
        url="https://www.anthropic.com/research/drug-discovery",
        published_at=now,
        categories=["Research"],
    )
    assert res_article.is_research is True
    assert res_article.is_engineering is False
    assert res_article.is_news is False
    assert res_article.primary_category == "Research"
    assert res_article.matches_category("research") is True
    assert res_article.matches_category("Engineering") is False

    eng_article = AnthropicArticle(
        article_id="2",
        title="Scaling Source Control",
        url="https://www.anthropic.com/engineering/source-control",
        published_at=now,
        categories=["Engineering"],
    )
    assert eng_article.is_research is False
    assert eng_article.is_engineering is True
    assert eng_article.primary_category == "Engineering"

    news_article = AnthropicArticle(
        article_id="3",
        title="New Office Opening",
        url="https://www.anthropic.com/news/new-office",
        published_at=now,
        categories=["News"],
    )
    assert news_article.is_news is True
    assert news_article.primary_category == "News"


def test_anthropic_article_timezone_normalization():
    """Ensure naive datetimes are automatically assigned UTC timezone."""
    naive_dt = datetime(2026, 10, 28, 12, 0, 0)
    article = AnthropicArticle(
        article_id="10",
        title="Timezone Test",
        url="https://www.anthropic.com/news/timezone-test",
        published_at=naive_dt,
    )
    assert article.published_at.tzinfo == timezone.utc


def test_anthropic_article_to_markdown():
    """Test single article markdown generation."""
    pub_dt = datetime(2026, 10, 28, 10, 30, tzinfo=timezone.utc)
    article = AnthropicArticle(
        article_id="test_guid",
        title="Testing Claude Capabilities",
        url="https://www.anthropic.com/research/testing-claude",
        published_at=pub_dt,
        summary="A study evaluating agentic coding capabilities.",
        categories=["Research", "Engineering"],
        author="Anthropic",
    )
    md = article.to_markdown()

    assert "### [Testing Claude Capabilities](https://www.anthropic.com/research/testing-claude)" in md
    assert "- **Categories:** `Research`, `Engineering`" in md
    assert "- **Published:** 2026-10-28 10:30 UTC" in md
    assert "- **Author:** Anthropic" in md
    assert "#### Summary" in md
    assert "> A study evaluating agentic coding capabilities." in md


def test_anthropic_category_normalization():
    """Test normalization of category strings."""
    assert AnthropicCategory.from_string("research") == "Research"
    assert AnthropicCategory.from_string("ENGINEERING") == "Engineering"
    assert AnthropicCategory.from_string("news") == "News"
    assert AnthropicCategory.from_string("custom tag") == "Custom Tag"


# ---------------------------------------------------------------------------
# Filter Criteria Tests
# ---------------------------------------------------------------------------
def test_filter_by_hours_back(sample_articles):
    """Test filtering articles by 24h cutoff."""
    criteria = AnthropicFilterCriteria(hours_back=24)
    filtered = AnthropicArticleFilter.filter(sample_articles, criteria)

    # First two articles are within 24h
    assert len(filtered) == 2
    titles = [a.title for a in filtered]
    assert "Early progress on accelerating drug development with Claude" in titles
    assert "Redesigning source control at Anthropic" in titles


def test_filter_by_category(sample_articles):
    """Test filtering by category."""
    research_only = AnthropicArticleFilter.filter_by_category(sample_articles, "Research", hours=None)
    assert len(research_only) == 2
    for art in research_only:
        assert art.is_research

    eng_only = AnthropicArticleFilter.filter_by_category(sample_articles, "Engineering", hours=None)
    assert len(eng_only) == 1
    assert eng_only[0].title == "Redesigning source control at Anthropic"


def test_filter_research_and_engineering_focus(sample_articles):
    """Test the focus filter covering Research and Engineering within 24h."""
    focused_24h = AnthropicArticleFilter.filter_research_and_engineering(sample_articles, hours=24)
    assert len(focused_24h) == 2
    for art in focused_24h:
        assert art.is_research or art.is_engineering


def test_filter_keyword_search(sample_articles):
    """Test keyword searching in title or summary."""
    criteria = AnthropicFilterCriteria(hours_back=None, search_query="source control")
    matched = AnthropicArticleFilter.filter(sample_articles, criteria)
    assert len(matched) == 1
    assert "source control" in matched[0].title.lower()


def test_filter_limit(sample_articles):
    """Test limit constraint."""
    criteria = AnthropicFilterCriteria(hours_back=None, limit=2)
    matched = AnthropicArticleFilter.filter(sample_articles, criteria)
    assert len(matched) == 2


# ---------------------------------------------------------------------------
# Feed Parser & Deduplication Tests
# ---------------------------------------------------------------------------
MOCK_NEWS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Anthropic News</title>
    <link>https://www.anthropic.com/news</link>
    <description>News updates from Anthropic</description>
    <item>
      <title>Expanding our partnership with AWS</title>
      <link>https://www.anthropic.com/news/expanding-partnership-aws?utm_source=rss</link>
      <guid>https://www.anthropic.com/news/expanding-partnership-aws</guid>
      <pubDate>Tue, 27 Oct 2026 00:00:00 +0000</pubDate>
      <description>&lt;p&gt;AWS and Anthropic are expanding their collaborative efforts.&lt;/p&gt;</description>
      <category>News</category>
    </item>
    <item>
      <title>Shared Article in News and Research</title>
      <link>https://www.anthropic.com/research/shared-study</link>
      <guid>https://www.anthropic.com/research/shared-study</guid>
      <pubDate>Mon, 26 Oct 2026 12:00:00 +0000</pubDate>
      <description>Breakthrough multi-agent collaboration study.</description>
      <category>News</category>
    </item>
  </channel>
</rss>
"""

MOCK_RESEARCH_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>Anthropic Research</title>
    <link>https://www.anthropic.com/research</link>
    <description>Research papers and findings</description>
    <item>
      <title>Shared Article in News and Research</title>
      <link>https://www.anthropic.com/research/shared-study</link>
      <guid>https://www.anthropic.com/research/shared-study</guid>
      <pubDate>Mon, 26 Oct 2026 12:00:00 +0000</pubDate>
      <description>Breakthrough multi-agent collaboration study.</description>
      <category>Research</category>
    </item>
    <item>
      <title>Unique Research Finding</title>
      <link>https://www.anthropic.com/research/unique-finding</link>
      <guid>https://www.anthropic.com/research/unique-finding</guid>
      <pubDate>Sun, 25 Oct 2026 10:00:00 +0000</pubDate>
      <description>Novel interpretability techniques.</description>
      <category>Research</category>
    </item>
  </channel>
</rss>
"""


def test_feed_parser_deduplication_and_category_merging():
    """Verify that duplicate articles across feeds are merged and categories combined."""
    mock_client = MagicMock()

    def mock_get(url):
        response = MagicMock()
        response.status_code = 200
        if "news" in url:
            response.content = MOCK_NEWS_XML.encode("utf-8")
        else:
            response.content = MOCK_RESEARCH_XML.encode("utf-8")
        return response

    mock_client.get.side_effect = mock_get

    custom_feeds = {
        "news": "https://example.com/feed_news.xml",
        "research": "https://example.com/feed_research.xml",
    }

    parser = AnthropicFeedParser(client=mock_client, feeds=custom_feeds)
    articles = parser.fetch_all_feeds()

    # Total unique articles should be 3:
    # 1. Expanding our partnership with AWS (from news)
    # 2. Shared Article in News and Research (in both feeds)
    # 3. Unique Research Finding (from research)
    assert len(articles) == 3

    shared_article = next(a for a in articles if a.url == "https://www.anthropic.com/research/shared-study")
    assert "News" in shared_article.categories
    assert "Research" in shared_article.categories
    assert shared_article.is_research is True
    assert shared_article.is_news is True


def test_feed_parser_url_cleaning():
    """Verify URL query stripping."""
    assert (
        AnthropicFeedParser._clean_url("https://www.anthropic.com/news/update?utm_source=rss&ref=test#heading")
        == "https://www.anthropic.com/news/update"
    )
    assert (
        AnthropicFeedParser._clean_url("https://www.anthropic.com/engineering/post/")
        == "https://www.anthropic.com/engineering/post"
    )


# ---------------------------------------------------------------------------
# Scraper Service Tests
# ---------------------------------------------------------------------------
def test_anthropic_scraper_service_markdown_export(sample_articles):
    """Test generating full Markdown document for Anthropic articles."""
    service = AnthropicScraperService()
    md = service.export_markdown(sample_articles[:2])

    assert "# Anthropic News & Research Digest" in md
    assert "🔬 Research Focus" in md
    assert "⚙️ Engineering & Architecture" in md
    assert "Early progress on accelerating drug development with Claude" in md
    assert "Redesigning source control at Anthropic" in md
    assert "Total Articles:" in md


def test_anthropic_article_with_full_content():
    """Verify AnthropicArticle with full content attached and markdown rendering."""
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    art = AnthropicArticle(
        article_id="ant_full_1",
        title="Drug Discovery with Claude",
        url="https://www.anthropic.com/research/drug-discovery",
        published_at=now,
        summary="Short excerpt",
        content="## Biology Research\n\nFull study on molecule generation.",
        word_count=8,
        categories=["Research"],
    )

    assert art.has_full_content is True
    md = art.to_markdown()
    assert "#### Full Article Content (8 words)" in md
    assert "## Biology Research" in md
    assert "Full study on molecule generation." in md


def test_anthropic_scraper_service_fetch_article_content():
    """Test fetch_article_content via AnthropicScraperService."""
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    art = AnthropicArticle(
        article_id="ant_test",
        title="Test Article",
        url="https://www.anthropic.com/engineering/test",
        published_at=now,
    )

    service = AnthropicScraperService()
    mock_extracted = MagicMock()
    mock_extracted.success = True
    mock_extracted.markdown = "# Extracted Anthropic Body"
    mock_extracted.word_count = 150

    with patch.object(service.content_extractor, "fetch_content", return_value=mock_extracted):
        service.fetch_article_content(art)

    assert art.has_full_content is True
    assert art.content == "# Extracted Anthropic Body"
    assert art.word_count == 150


