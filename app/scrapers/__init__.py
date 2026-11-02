"""Scrapers and data ingestion modules."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.scrapers.anthropic import (
        AnthropicArticleFilter,
        AnthropicFeedParser,
        AnthropicScraperService,
        get_daily_anthropic_articles,
        get_daily_anthropic_focus,
    )
    from app.scrapers.openai import (
        OpenAIArticleFilter,
        OpenAIFeedParser,
        OpenAIScraperService,
        get_daily_openai_articles,
        get_daily_openai_focus,
    )
    from app.scrapers.runner import (
        AggregationResult,
        AggregationRunner,
        run_news_aggregation,
    )
    from app.scrapers.youtube import YouTubeService, YouTubeVideo

__all__ = [
    "YouTubeService",
    "YouTubeVideo",
    "OpenAIScraperService",
    "OpenAIFeedParser",
    "OpenAIArticleFilter",
    "get_daily_openai_articles",
    "get_daily_openai_focus",
    "AnthropicScraperService",
    "AnthropicFeedParser",
    "AnthropicArticleFilter",
    "get_daily_anthropic_articles",
    "get_daily_anthropic_focus",
    "AggregationRunner",
    "AggregationResult",
    "run_news_aggregation",
]


def __getattr__(name: str):
    """Lazy import scraper classes and helpers without triggering runpy warnings."""
    if name in ("YouTubeService", "YouTubeVideo"):
        from app.scrapers.youtube import YouTubeService, YouTubeVideo
        return locals()[name]
    if name in (
        "OpenAIScraperService",
        "OpenAIFeedParser",
        "OpenAIArticleFilter",
        "get_daily_openai_articles",
        "get_daily_openai_focus",
    ):
        import app.scrapers.openai as oai
        return getattr(oai, name)
    if name in (
        "AnthropicScraperService",
        "AnthropicFeedParser",
        "AnthropicArticleFilter",
        "get_daily_anthropic_articles",
        "get_daily_anthropic_focus",
    ):
        import app.scrapers.anthropic as ant
        return getattr(ant, name)
    if name in (
        "AggregationRunner",
        "AggregationResult",
        "run_news_aggregation",
    ):
        import app.scrapers.runner as run
        return getattr(run, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
