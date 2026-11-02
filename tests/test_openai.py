"""Unit tests for OpenAI Scraper Service, Feed Parser, and Pydantic models."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.models.openai import (
    OpenAIArticle,
    OpenAICategory,
    OpenAIFilterCriteria,
)
from app.scrapers.openai import (
    OpenAIArticleFilter,
    OpenAIFeedParser,
    OpenAIScraperService,
)


@pytest.fixture
def sample_articles():
    now = datetime.now(timezone.utc)
    return [
        OpenAIArticle(
            article_id="art_1",
            title="Frontier Math: A Benchmark for Evaluating Advanced Mathematical Reasoning",
            url="https://openai.com/index/frontier-math/?utm_source=chatgpt.com",
            published_at=now - timedelta(hours=3),
            summary="New research benchmark for mathematics.",
            categories=["Research"],
            author="OpenAI",
        ),
        OpenAIArticle(
            article_id="art_2",
            title="Rapidly scaling online storage to serve over 1 billion users",
            url="https://openai.com/index/scaling-storage-one-billion-users/",
            published_at=now - timedelta(hours=12),
            summary="Engineering deep dive into infrastructure.",
            categories=["Engineering"],
            author="OpenAI Engineering",
        ),
        OpenAIArticle(
            article_id="art_3",
            title="OpenAI and Broadcom Partner on Custom Silicon",
            url="https://openai.com/index/openai-broadcom-partnership",
            published_at=now - timedelta(hours=30),  # Older than 24h
            summary="Company business announcement.",
            categories=["Company"],
            author="OpenAI",
        ),
        OpenAIArticle(
            article_id="art_4",
            title="Older Research Paper on Alignment",
            url="https://openai.com/index/older-alignment-research",
            published_at=now - timedelta(days=5),
            summary="Alignment research paper from last week.",
            categories=["Research", "Safety"],
            author="OpenAI",
        ),
    ]


# ---------------------------------------------------------------------------
# Pydantic Model Tests
# ---------------------------------------------------------------------------
def test_openai_article_model_properties():
    """Verify OpenAIArticle properties and category detection."""
    now = datetime.now(timezone.utc)
    res_article = OpenAIArticle(
        article_id="1",
        title="Test Research",
        url="https://openai.com/index/test-research",
        published_at=now,
        categories=["Research"],
    )
    assert res_article.is_research is True
    assert res_article.is_engineering is False
    assert res_article.primary_category == "Research"
    assert res_article.matches_category("research") is True
    assert res_article.matches_category("Engineering") is False

    eng_article = OpenAIArticle(
        article_id="2",
        title="Test Engineering",
        url="https://openai.com/index/test-engineering",
        published_at=now,
        categories=["Engineering"],
    )
    assert eng_article.is_research is False
    assert eng_article.is_engineering is True


def test_openai_article_timezone_normalization():
    """Ensure naive datetimes are automatically assigned UTC timezone."""
    naive_dt = datetime(2026, 10, 30, 12, 0, 0)
    article = OpenAIArticle(
        article_id="10",
        title="Timezone Test",
        url="https://openai.com/index/timezone-test",
        published_at=naive_dt,
    )
    assert article.published_at.tzinfo == timezone.utc


def test_filter_criteria_cutoff():
    """Verify FilterCriteria cutoff_datetime calculation."""
    criteria = OpenAIFilterCriteria(hours_back=24)
    cutoff = criteria.cutoff_datetime
    assert cutoff is not None
    assert cutoff.tzinfo == timezone.utc
    assert datetime.now(timezone.utc) - cutoff < timedelta(hours=24, seconds=5)


# ---------------------------------------------------------------------------
# URL Cleaning Tests
# ---------------------------------------------------------------------------
def test_clean_url():
    """Verify that tracking query parameters are cleanly stripped."""
    raw = "https://openai.com/index/helping-websites-express-ai-training-preferences?utm_source=chatgpt.com&ref=feed"
    clean = OpenAIFeedParser._clean_url(raw)
    assert clean == "https://openai.com/index/helping-websites-express-ai-training-preferences"


# ---------------------------------------------------------------------------
# ArticleFilter Tests
# ---------------------------------------------------------------------------
def test_filter_by_time_24_hours(sample_articles):
    """Articles published within 24 hours should be retained."""
    criteria = OpenAIFilterCriteria(hours_back=24)
    filtered = OpenAIArticleFilter.apply(sample_articles, criteria)
    assert len(filtered) == 2
    assert [a.article_id for a in filtered] == ["art_1", "art_2"]


def test_filter_by_category_research(sample_articles):
    """Filter specifically for Research articles."""
    criteria = OpenAIFilterCriteria(hours_back=None, categories=["Research"])
    filtered = OpenAIArticleFilter.apply(sample_articles, criteria)
    assert len(filtered) == 2
    assert all("Research" in a.categories for a in filtered)


def test_filter_by_category_engineering(sample_articles):
    """Filter specifically for Engineering articles."""
    criteria = OpenAIFilterCriteria(hours_back=None, categories=["Engineering"])
    filtered = OpenAIArticleFilter.apply(sample_articles, criteria)
    assert len(filtered) == 1
    assert filtered[0].article_id == "art_2"


def test_filter_focus_areas_research_and_engineering(sample_articles):
    """Filter for both Research and Engineering simultaneously."""
    criteria = OpenAIFilterCriteria(
        hours_back=24,
        categories=["Research", "Engineering"],
    )
    filtered = OpenAIArticleFilter.apply(sample_articles, criteria)
    assert len(filtered) == 2
    assert set(a.article_id for a in filtered) == {"art_1", "art_2"}


def test_filter_search_query(sample_articles):
    """Filter articles by search keyword in title or summary."""
    criteria = OpenAIFilterCriteria(
        hours_back=None,
        search_query="mathematics",
    )
    filtered = OpenAIArticleFilter.apply(sample_articles, criteria)
    assert len(filtered) == 1
    assert filtered[0].article_id == "art_1"


# ---------------------------------------------------------------------------
# Scraper Service Tests with Mock Feed
# ---------------------------------------------------------------------------
def test_feed_parser_with_mock_xml():
    """Verify parsing of valid RSS feed XML into OpenAIArticle models."""
    mock_rss_xml = """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0">
        <channel>
            <title>OpenAI News</title>
            <link>https://openai.com/news/</link>
            <description>Latest news from OpenAI</description>
            <item>
                <title>Introducing GPT-5: A Step Towards AGI</title>
                <link>https://openai.com/index/introducing-gpt-5?utm_source=chatgpt.com</link>
                <guid>https://openai.com/index/introducing-gpt-5</guid>
                <pubDate>Mon, 02 Nov 2026 10:00:00 GMT</pubDate>
                <description>We are thrilled to announce GPT-5.</description>
                <category>Research</category>
                <category>Product</category>
            </item>
        </channel>
    </rss>
    """
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.content = mock_rss_xml.encode("utf-8")
    mock_client.get.return_value = mock_response

    parser = OpenAIFeedParser(mock_client)
    articles = parser.fetch_articles()

    assert len(articles) == 1
    art = articles[0]
    assert art.title == "Introducing GPT-5: A Step Towards AGI"
    assert art.url == "https://openai.com/index/introducing-gpt-5"  # stripped tracking query
    assert art.is_research is True
    assert "Product" in art.categories
    assert art.summary == "We are thrilled to announce GPT-5."
    assert art.published_at.year == 2026


def test_openai_article_with_full_content():
    """Verify OpenAIArticle with full content attached and markdown rendering."""
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    art = OpenAIArticle(
        article_id="art_full_1",
        title="Misalignment Monitoring",
        url="https://openai.com/index/misalignment",
        published_at=now,
        summary="Short excerpt",
        content="## Architecture\n\nFull details of layer monitoring.",
        word_count=7,
        categories=["Research"],
    )

    assert art.has_full_content is True
    md = art.to_markdown()
    assert "#### Full Article Content (7 words)" in md
    assert "## Architecture" in md
    assert "Full details of layer monitoring." in md


def test_scraper_service_fetch_article_content():
    """Test fetch_article_content via OpenAIScraperService."""
    now = datetime(2026, 11, 2, 10, 0, tzinfo=timezone.utc)
    art = OpenAIArticle(
        article_id="art_test",
        title="Test Article",
        url="https://openai.com/index/test",
        published_at=now,
    )

    service = OpenAIScraperService()
    mock_extracted = MagicMock()
    mock_extracted.success = True
    mock_extracted.markdown = "# Extracted Article Body"
    mock_extracted.word_count = 120

    with patch.object(service.content_extractor, "fetch_content", return_value=mock_extracted):
        service.fetch_article_content(art)

    assert art.has_full_content is True
    assert art.content == "# Extracted Article Body"
    assert art.word_count == 120


