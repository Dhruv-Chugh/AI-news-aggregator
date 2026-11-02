"""Anthropic News, Research & Engineering Scraper Service (OOP & Pydantic Architecture).

Fetches, validates, deduplicates, and filters articles from the 3 Anthropic RSS feeds:
- News: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml
- Engineering: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml
- Research: https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml

Provides unified scraping, time-window filtering (e.g. 24h), search, and Markdown export.
"""

from __future__ import annotations

import argparse
import html
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse, urlunparse

import dateutil.parser
import feedparser
import httpx

from app.models.anthropic import (
    AnthropicArticle,
    AnthropicCategory,
    AnthropicFilterCriteria,
)
from app.services.content_extractor import ArticleContentExtractor

logger = logging.getLogger("ai_news.anthropic")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

DEFAULT_ANTHROPIC_FEEDS: Dict[str, str] = {
    "news": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml",
    "engineering": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml",
    "research": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_research.xml",
}


class AnthropicFeedParser:
    """Class responsible for retrieving and parsing Anthropic's RSS feeds into Pydantic models."""

    def __init__(
        self,
        client: httpx.Client,
        feeds: Optional[Dict[str, str]] = None,
    ) -> None:
        self.client = client
        self.feeds = feeds or DEFAULT_ANTHROPIC_FEEDS.copy()

    def fetch_single_feed(self, feed_name: str, feed_url: str) -> List[AnthropicArticle]:
        """Fetch a specific Anthropic RSS feed and parse entries into validated AnthropicArticle models."""
        logger.debug("Fetching Anthropic %s feed from: %s", feed_name, feed_url)

        try:
            response = self.client.get(feed_url)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
            else:
                logger.warning(
                    "HTTP %d when fetching Anthropic %s feed, falling back to feedparser",
                    response.status_code,
                    feed_name,
                )
                feed = feedparser.parse(feed_url)
        except Exception as e:
            logger.error("Network error fetching Anthropic %s feed (%s): %s", feed_name, feed_url, e)
            try:
                feed = feedparser.parse(feed_url)
            except Exception as inner_e:
                logger.error("Fatal error parsing Anthropic %s feed: %s", feed_name, inner_e)
                return []

        if feed.bozo and not feed.entries:
            logger.warning("Feedparser error for Anthropic %s feed: %s", feed_name, feed.get("bozo_exception"))
            return []

        articles: List[AnthropicArticle] = []

        for entry in feed.entries:
            try:
                # Unique ID or URL
                article_id = entry.get("id") or entry.get("link") or ""
                if not article_id:
                    continue

                title = entry.get("title", "Untitled Anthropic Post").strip()
                title = html.unescape(title)

                raw_link = entry.get("link", "")
                clean_url = self._clean_url(raw_link)

                # Published date parsing
                pub_raw = entry.get("published") or entry.get("updated")
                if pub_raw:
                    pub_dt = dateutil.parser.parse(pub_raw)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    else:
                        pub_dt = pub_dt.astimezone(timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)

                # Summary / Description
                summary = ""
                if "summary" in entry:
                    summary = entry.summary
                elif "summary_detail" in entry and "value" in entry.summary_detail:
                    summary = entry.summary_detail.value
                elif "description" in entry:
                    summary = entry.description

                summary = self._clean_summary(summary)

                # Categories / Tags
                categories: List[str] = []
                if "tags" in entry and entry.tags:
                    for tag in entry.tags:
                        term = getattr(tag, "term", None) or (tag.get("term") if isinstance(tag, dict) else None)
                        if term:
                            normalized = AnthropicCategory.from_string(term)
                            if normalized not in categories:
                                categories.append(normalized)

                # Fallback category based on feed name or URL
                default_cat = AnthropicCategory.from_string(feed_name)
                if not categories:
                    categories.append(default_cat)
                elif default_cat not in categories:
                    # Append default feed tag if not already represented
                    categories.append(default_cat)

                author = entry.get("author") or "Anthropic"

                article = AnthropicArticle(
                    article_id=article_id,
                    title=title,
                    url=clean_url or raw_link,
                    published_at=pub_dt,
                    summary=summary,
                    categories=categories,
                    author=author,
                    feed_source=feed_name,
                )
                articles.append(article)
            except Exception as e:
                logger.debug("Skipping invalid Anthropic article entry: %s", e)
                continue

        logger.debug("Parsed %d articles from %s feed", len(articles), feed_name)
        return articles

    def fetch_all_feeds(self, feeds: Optional[Dict[str, str]] = None) -> List[AnthropicArticle]:
        """Fetch all configured Anthropic feeds and deduplicate entries across feeds."""
        target_feeds = feeds or self.feeds
        merged_by_url: Dict[str, AnthropicArticle] = {}

        for feed_name, feed_url in target_feeds.items():
            feed_articles = self.fetch_single_feed(feed_name, feed_url)

            for art in feed_articles:
                key = art.url or art.article_id
                if key in merged_by_url:
                    # Article already present from another feed: merge categories
                    existing = merged_by_url[key]
                    merged_categories = list(dict.fromkeys(existing.categories + art.categories))
                    existing.categories = merged_categories
                else:
                    merged_by_url[key] = art

        all_articles = list(merged_by_url.values())
        all_articles.sort(key=lambda a: a.published_at, reverse=True)
        logger.info("Retrieved %d unique Anthropic articles across %d feeds", len(all_articles), len(target_feeds))
        return all_articles

    @staticmethod
    def _clean_url(raw_url: str) -> str:
        """Strip tracking query parameters and normalize URL."""
        if not raw_url:
            return ""
        parsed = urlparse(raw_url.strip())
        clean_path = parsed.path.rstrip("/") if parsed.path != "/" else "/"
        return urlunparse((parsed.scheme, parsed.netloc, clean_path, "", "", ""))

    @staticmethod
    def _clean_summary(raw_summary: str) -> str:
        """Clean HTML tags and decode entities in summary."""
        if not raw_summary:
            return ""
        cleaned = html.unescape(raw_summary)
        # Strip simple HTML paragraph tags if present
        cleaned = cleaned.replace("<p>", "").replace("</p>", "\n").strip()
        return cleaned


class AnthropicArticleFilter:
    """Class responsible for filtering Anthropic articles by timeframe, category, and keywords."""

    @staticmethod
    def filter(
        articles: List[AnthropicArticle],
        criteria: AnthropicFilterCriteria,
    ) -> List[AnthropicArticle]:
        """Apply full Pydantic filter criteria to a list of Anthropic articles."""
        filtered = [art for art in articles if criteria.matches(art)]
        if criteria.limit and criteria.limit > 0:
            filtered = filtered[: criteria.limit]
        return filtered

    @staticmethod
    def filter_by_hours(articles: List[AnthropicArticle], hours: int) -> List[AnthropicArticle]:
        """Filter articles published within the last N hours."""
        criteria = AnthropicFilterCriteria(hours_back=hours)
        return AnthropicArticleFilter.filter(articles, criteria)

    @staticmethod
    def filter_research_and_engineering(
        articles: List[AnthropicArticle],
        hours: Optional[int] = None,
    ) -> List[AnthropicArticle]:
        """Filter articles specifically belonging to Research or Engineering."""
        criteria = AnthropicFilterCriteria(
            hours_back=hours,
            categories=["Research", "Engineering"],
        )
        return AnthropicArticleFilter.filter(articles, criteria)

    @staticmethod
    def filter_by_category(
        articles: List[AnthropicArticle],
        category: str,
        hours: Optional[int] = None,
    ) -> List[AnthropicArticle]:
        """Filter articles belonging to a specific category."""
        criteria = AnthropicFilterCriteria(
            hours_back=hours,
            categories=[category],
        )
        return AnthropicArticleFilter.filter(articles, criteria)


class AnthropicScraperService:
    """High-level service coordinating Anthropic feed retrieval, filtering, and export."""

    def __init__(
        self,
        client: Optional[httpx.Client] = None,
        feeds: Optional[Dict[str, str]] = None,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.Client(
            timeout=15.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        self.parser = AnthropicFeedParser(client=self.client, feeds=feeds)
        self.filter = AnthropicArticleFilter()
        self.content_extractor = ArticleContentExtractor(client=self.client)

    def __enter__(self) -> AnthropicScraperService:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close HTTP client if owned by this service instance."""
        if self._owns_client:
            self.client.close()

    def fetch_article_content(self, article: AnthropicArticle) -> AnthropicArticle:
        """Fetch full article content from original anthropic.com website and attach to article model."""
        extracted = self.content_extractor.fetch_content(article.url)
        if extracted.success and extracted.markdown:
            article.content = extracted.markdown
            article.word_count = extracted.word_count
            logger.info("Successfully fetched %d words for '%s'", extracted.word_count, article.title)
        else:
            logger.warning("Could not extract full content for '%s': %s", article.title, extracted.error_message)
        return article

    def get_articles(
        self,
        hours_back: Optional[int] = 24,
        categories: Optional[List[str]] = None,
        search_query: Optional[str] = None,
        limit: Optional[int] = None,
        feed_name: Optional[str] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Retrieve and filter Anthropic articles according to criteria, optionally fetching full webpage content.

        Args:
            hours_back: Number of hours to look back (default 24). None or <= 0 for all history.
            categories: List of categories to match (e.g. ['Research', 'Engineering']).
            search_query: Optional string to match in title or summary.
            limit: Maximum number of articles to return.
            feed_name: Optional single feed to scrape ('news', 'engineering', 'research').
            fetch_full_content: Whether to fetch and parse the complete article body from anthropic.com.
        """
        if feed_name and feed_name in self.parser.feeds:
            articles = self.parser.fetch_single_feed(feed_name, self.parser.feeds[feed_name])
            articles.sort(key=lambda a: a.published_at, reverse=True)
        else:
            articles = self.parser.fetch_all_feeds()

        criteria = AnthropicFilterCriteria(
            hours_back=hours_back,
            categories=categories or [],
            search_query=search_query,
            limit=limit,
        )
        filtered = self.filter.filter(articles, criteria)

        if fetch_full_content:
            logger.info("Fetching full article content from original website for %d articles...", len(filtered))
            for art in filtered:
                self.fetch_article_content(art)

        return filtered

    def get_latest_articles(
        self,
        limit: int = 10,
        feed_name: Optional[str] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Get the most recent articles across all Anthropic feeds without time cutoff."""
        return self.get_articles(
            hours_back=None,
            limit=limit,
            feed_name=feed_name,
            fetch_full_content=fetch_full_content,
        )

    def get_research_articles(
        self,
        hours_back: Optional[int] = None,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Get Anthropic Research articles."""
        return self.get_articles(
            hours_back=hours_back,
            categories=["Research"],
            limit=limit,
            fetch_full_content=fetch_full_content,
        )

    def get_engineering_articles(
        self,
        hours_back: Optional[int] = None,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Get Anthropic Engineering articles."""
        return self.get_articles(
            hours_back=hours_back,
            categories=["Engineering"],
            limit=limit,
            fetch_full_content=fetch_full_content,
        )

    def get_news_articles(
        self,
        hours_back: Optional[int] = None,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Get Anthropic News / Company announcements."""
        return self.get_articles(
            hours_back=hours_back,
            categories=["News"],
            limit=limit,
            fetch_full_content=fetch_full_content,
        )

    def get_focus_articles(
        self,
        hours_back: Optional[int] = 24,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[AnthropicArticle]:
        """Get articles specifically focused on Research and Engineering."""
        return self.get_articles(
            hours_back=hours_back,
            categories=["Research", "Engineering"],
            limit=limit,
            fetch_full_content=fetch_full_content,
        )

    def export_markdown(
        self,
        articles: List[AnthropicArticle],
        output_path: Optional[str] = None,
    ) -> str:
        """Format articles into a GitHub-Flavored Markdown document."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        total = len(articles)

        research_count = sum(1 for a in articles if a.is_research)
        eng_count = sum(1 for a in articles if a.is_engineering)
        news_count = sum(1 for a in articles if a.is_news)
        other_count = total - (research_count + eng_count + news_count)
        if other_count < 0:
            other_count = 0

        lines: List[str] = [
            "# Anthropic News & Research Digest",
            "",
            f"> **Generated:** `{now_str}` | **Total Articles:** `{total}`",
            f"> **Breakdown:** `{research_count}` Research, `{eng_count}` Engineering, `{news_count}` News",
            "",
            "---",
            "",
        ]

        if not articles:
            lines.append("_No Anthropic articles found matching the specified criteria._\n")
            doc = "\n".join(lines)
        else:
            research_items = [a for a in articles if a.is_research]
            engineering_items = [a for a in articles if a.is_engineering]
            news_items = [a for a in articles if not a.is_research and not a.is_engineering]

            index = 1
            if research_items:
                lines.extend(["## 🔬 Research Focus", ""])
                for art in research_items:
                    lines.append(f"### {index}. [{art.title}]({art.url})")
                    lines.append(f"- **Categories:** {', '.join(f'`{c}`' for c in art.categories)}")
                    lines.append(f"- **Published:** {art.published_at.strftime('%Y-%m-%d %H:%M UTC')}")
                    lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                    lines.append("")
                    if art.has_full_content and art.content:
                        w_cnt = art.word_count or len(art.content.split())
                        lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                        lines.append(art.content)
                    else:
                        lines.append("#### Abstract / Summary")
                        lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                    lines.append("")
                    lines.append("---")
                    lines.append("")
                    index += 1

            if engineering_items:
                lines.extend(["## ⚙️ Engineering & Architecture", ""])
                for art in engineering_items:
                    lines.append(f"### {index}. [{art.title}]({art.url})")
                    lines.append(f"- **Categories:** {', '.join(f'`{c}`' for c in art.categories)}")
                    lines.append(f"- **Published:** {art.published_at.strftime('%Y-%m-%d %H:%M UTC')}")
                    lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                    lines.append("")
                    if art.has_full_content and art.content:
                        w_cnt = art.word_count or len(art.content.split())
                        lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                        lines.append(art.content)
                    else:
                        lines.append("#### Summary")
                        lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                    lines.append("")
                    lines.append("---")
                    lines.append("")
                    index += 1

            if news_items:
                lines.extend(["## 📢 News & Announcements", ""])
                for art in news_items:
                    lines.append(f"### {index}. [{art.title}]({art.url})")
                    cats_str = ", ".join(f"`{c}`" for c in art.categories) if art.categories else "`News`"
                    lines.append(f"- **Categories:** {cats_str}")
                    lines.append(f"- **Published:** {art.published_at.strftime('%Y-%m-%d %H:%M UTC')}")
                    lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                    lines.append("")
                    if art.has_full_content and art.content:
                        w_cnt = art.word_count or len(art.content.split())
                        lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                        lines.append(art.content)
                    else:
                        lines.append("#### Summary")
                        lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                    lines.append("")
                    lines.append("---")
                    lines.append("")
                    index += 1

            doc = "\n".join(lines)

        if output_path:
            p = Path(output_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(doc, encoding="utf-8")
            logger.info("Exported Anthropic digest to %s", p.resolve())

        return doc


def get_daily_anthropic_articles(
    hours_back: int = 24,
    limit: Optional[int] = None,
) -> List[AnthropicArticle]:
    """Convenience function: retrieve Anthropic articles from the last N hours."""
    with AnthropicScraperService() as service:
        return service.get_articles(hours_back=hours_back, limit=limit)


def get_daily_anthropic_focus(
    hours_back: int = 24,
    limit: Optional[int] = None,
) -> List[AnthropicArticle]:
    """Convenience function: retrieve Anthropic Research & Engineering articles."""
    with AnthropicScraperService() as service:
        return service.get_focus_articles(hours_back=hours_back, limit=limit)


def main() -> None:
    """CLI entry point for testing and executing Anthropic RSS scraping."""
    # Ensure UTF-8 output on Windows consoles
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Anthropic News, Research, & Engineering Scraper Service",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--hours",
        type=int,
        default=24,
        help="Filter articles published in the last N hours (0 for all history)",
    )
    parser.add_argument(
        "--feed",
        type=str,
        default="all",
        choices=["all", "news", "engineering", "research"],
        help="Target a specific Anthropic feed",
    )
    parser.add_argument(
        "--category",
        type=str,
        default="all",
        help="Filter by category ('news', 'research', 'engineering', 'safety', etc.)",
    )
    parser.add_argument(
        "--focus",
        action="store_true",
        help="Focus on Research and Engineering articles only",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Keyword search in title or summary",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of output articles",
    )
    parser.add_argument(
        "--fetch-content",
        "-C",
        action="store_true",
        help="Fetch full article content directly from original anthropic.com website",
    )
    parser.add_argument(
        "--markdown",
        action="store_true",
        help="Print results formatted as GitHub-Flavored Markdown",
    )
    parser.add_argument(
        "--export-md",
        type=str,
        default=None,
        help="Save formatted Markdown output to specified file path",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Fetch all historical articles without time filtering",
    )

    args = parser.parse_args()

    hours_back = None if args.all or args.hours == 0 else args.hours

    categories: Optional[List[str]] = None
    if args.focus:
        categories = ["Research", "Engineering"]
    elif args.category and args.category.lower() not in ("all", "*"):
        categories = [args.category]

    feed_name = None if args.feed == "all" else args.feed

    print("\n🔍 Fetching Anthropic RSS feeds...")
    print(f"   - Target Feed: {args.feed}")
    print(f"   - Timeframe: {f'Last {hours_back} hours' if hours_back else 'All historical'}")
    print(f"   - Focus / Categories: {categories or 'All categories'}")
    if args.query:
        print(f"   - Search Query: '{args.query}'")
    print()

    with AnthropicScraperService() as service:
        articles = service.get_articles(
            hours_back=hours_back,
            categories=categories,
            search_query=args.query,
            limit=args.limit,
            feed_name=feed_name,
            fetch_full_content=args.fetch_content,
        )

        total = len(articles)
        print(f"✅ Found {total} matching Anthropic articles.")

        if args.markdown:
            print("\n" + service.export_markdown(articles))
        else:
            for idx, art in enumerate(articles, 1):
                pub_str = art.published_at.strftime("%Y-%m-%d %H:%M UTC")
                cats_str = ", ".join(art.categories) if art.categories else art.primary_category
                print(f"[{idx}] {art.title}")
                print(f"    Category:  {cats_str}")
                print(f"    Published: {pub_str} | Feed: {art.feed_source or 'multi'}")
                print(f"    Link:      {art.url}")
                if art.has_full_content and art.content:
                    word_cnt = art.word_count or len(art.content.split())
                    preview = art.content[:250].strip().replace("\n", " ")
                    print(f"    Full Text: [{word_cnt:,} words] \"{preview}...\"")
                elif art.summary:
                    snippet = art.summary[:140].replace("\n", " ")
                    print(f"    Summary:   \"{snippet}...\"")
                print()

        if args.export_md:
            service.export_markdown(articles, output_path=args.export_md)
            print(f"📁 Markdown document exported to: {args.export_md}")


if __name__ == "__main__":
    main()

