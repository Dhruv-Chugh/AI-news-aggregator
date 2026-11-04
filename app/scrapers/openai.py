"""OpenAI News & Blog Scraper Service (OOP & Pydantic Architecture).

Fetches, validates, and filters articles from the official OpenAI News RSS feed:
https://openai.com/news/rss.xml

Specifically designed to target and filter by OpenAI's primary focus areas:
- Research: https://openai.com/news/research/
- Engineering: https://openai.com/news/engineering/
as well as Product, Safety, Security, and Company announcements.
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timezone
from typing import Any, List, Optional
from urllib.parse import urlparse, urlunparse

import dateutil.parser
import feedparser
import httpx

from app.models.openai import (
    OpenAIArticle,
    OpenAICategory,
    OpenAIFilterCriteria,
)
from app.services.content_extractor import ArticleContentExtractor

logger = logging.getLogger("ai_news.openai")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

DEFAULT_OPENAI_RSS_URL = "https://openai.com/news/rss.xml"


class OpenAIFeedParser:
    """Class responsible for retrieving and parsing OpenAI's official RSS feed into Pydantic models."""

    def __init__(self, client: httpx.Client, feed_url: str = DEFAULT_OPENAI_RSS_URL) -> None:
        self.client = client
        self.feed_url = feed_url

    def fetch_articles(self) -> List[OpenAIArticle]:
        """Fetch the OpenAI RSS feed and parse all entries into validated OpenAIArticle models."""
        logger.debug("Fetching OpenAI RSS feed: %s", self.feed_url)

        try:
            response = self.client.get(self.feed_url)
            if response.status_code == 200:
                feed = feedparser.parse(response.content)
            else:
                logger.warning("HTTP %d when fetching OpenAI feed, falling back to feedparser", response.status_code)
                feed = feedparser.parse(self.feed_url)
        except Exception as e:
            logger.error("Network error fetching OpenAI feed %s: %s", self.feed_url, e)
            try:
                feed = feedparser.parse(self.feed_url)
            except Exception as inner_e:
                logger.error("Fatal error parsing OpenAI feed: %s", inner_e)
                return []

        if feed.bozo and not feed.entries:
            logger.warning("Feedparser error for OpenAI feed: %s", feed.get("bozo_exception"))
            return []

        articles: List[OpenAIArticle] = []

        for entry in feed.entries:
            try:
                # Article ID / GUID
                article_id = entry.get("id") or entry.get("link") or ""
                if not article_id:
                    continue

                # Title
                title = entry.get("title", "Untitled OpenAI Post").strip()

                # Clean Link (strip query parameters like ?utm_source=chatgpt.com)
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

                # Summary / Excerpt
                summary = ""
                if "summary" in entry:
                    summary = entry.summary
                elif "summary_detail" in entry and "value" in entry.summary_detail:
                    summary = entry.summary_detail.value

                # Categories / Tags
                categories: List[str] = []
                if "tags" in entry:
                    for tag in entry.tags:
                        term = tag.get("term")
                        if term and term.strip():
                            categories.append(term.strip())

                # Author
                author = "OpenAI"
                if "author_detail" in entry and "name" in entry.author_detail:
                    author = entry.author_detail.name
                elif "author" in entry and entry.author:
                    author = entry.author

                article_model = OpenAIArticle(
                    article_id=article_id,
                    title=title,
                    url=clean_url,
                    published_at=pub_dt,
                    summary=summary.strip(),
                    categories=categories,
                    author=author,
                )
                articles.append(article_model)

            except Exception as e:
                logger.warning("Error parsing OpenAI RSS entry: %s", e)
                continue

        # Sort newest first
        articles.sort(key=lambda a: a.published_at, reverse=True)
        return articles

    @staticmethod
    def _clean_url(url: str) -> str:
        """Strip tracking query parameters (e.g. utm_source) from article URL."""
        if not url:
            return ""
        parsed = urlparse(url)
        # Reconstruct URL without query and fragment
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path.rstrip("/"), "", "", ""))


class OpenAIArticleFilter:
    """Class responsible for filtering OpenAIArticle models by timeframe, category, and search terms."""

    @staticmethod
    def apply(articles: List[OpenAIArticle], criteria: OpenAIFilterCriteria) -> List[OpenAIArticle]:
        """Apply timeframe, category, and search query filters to a list of articles."""
        filtered = articles

        # 1. Filter by Publication Time Cutoff
        cutoff = criteria.cutoff_datetime
        if cutoff is not None:
            filtered = [a for a in filtered if a.published_at >= cutoff]

        # 2. Filter by Category (e.g. Research, Engineering)
        if criteria.categories:
            norm_cats = [c.strip().lower() for c in criteria.categories]
            filtered = [
                a for a in filtered
                if any(a.matches_category(target_cat) for target_cat in norm_cats)
            ]

        # 3. Filter by Keyword Search Query
        if criteria.search_query:
            query = criteria.search_query.strip().lower()
            filtered = [
                a for a in filtered
                if query in a.title.lower() or query in a.summary.lower()
            ]

        # 4. Limit results count if requested
        if criteria.limit is not None and criteria.limit > 0:
            filtered = filtered[: criteria.limit]

        return filtered


class OpenAIScraperService:
    """High-Level Object-Oriented Service for OpenAI article ingestion and filtering."""

    def __init__(
        self,
        feed_url: str = DEFAULT_OPENAI_RSS_URL,
        timeout: float = 15.0,
    ) -> None:
        """Initialize the OpenAIScraperService.

        Args:
            feed_url: OpenAI RSS feed URL (defaults to official https://openai.com/news/rss.xml).
            timeout: HTTP request timeout in seconds.
        """
        self.feed_url = feed_url
        self.timeout = timeout
        self.client = httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            },
        )
        self.feed_parser = OpenAIFeedParser(self.client, feed_url=feed_url)
        self.article_filter = OpenAIArticleFilter()
        self.content_extractor = ArticleContentExtractor(client=self.client)

    def close(self) -> None:
        """Close HTTP client."""
        self.client.close()

    def __enter__(self) -> "OpenAIScraperService":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def fetch_article_content(self, article: OpenAIArticle) -> OpenAIArticle:
        """Fetch full article content from original openai.com website and attach to article model."""
        extracted = self.content_extractor.fetch_content(article.url)
        if extracted.success and extracted.markdown:
            article.content = extracted.markdown
            article.word_count = extracted.word_count
            logger.info("Successfully fetched %d words for '%s'", extracted.word_count, article.title)
        else:
            logger.warning("Could not extract full content for '%s': %s", article.title, extracted.error_message)
        return article

    def fetch_all_articles(self) -> List[OpenAIArticle]:
        """Fetch all articles available in the OpenAI RSS feed."""
        return self.feed_parser.fetch_articles()

    def get_recent_articles(
        self,
        criteria: Optional[OpenAIFilterCriteria] = None,
        hours_back: Optional[int] = 24,
        fetch_full_content: bool = False,
    ) -> List[OpenAIArticle]:
        """Retrieve recent articles matching filter criteria, optionally fetching full webpage content."""
        filter_criteria = criteria or OpenAIFilterCriteria(hours_back=hours_back)
        articles = self.fetch_all_articles()
        filtered = self.article_filter.apply(articles, filter_criteria)

        if fetch_full_content:
            logger.info("Fetching full article content from original website for %d articles...", len(filtered))
            for art in filtered:
                self.fetch_article_content(art)

        return filtered

    def get_research_articles(
        self,
        hours_back: Optional[int] = 24,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[OpenAIArticle]:
        """Get articles specifically categorized under OpenAI Research (https://openai.com/news/research/)."""
        criteria = OpenAIFilterCriteria(
            hours_back=hours_back,
            categories=[OpenAICategory.RESEARCH.value],
            limit=limit,
        )
        return self.get_recent_articles(criteria=criteria, fetch_full_content=fetch_full_content)

    def get_engineering_articles(
        self,
        hours_back: Optional[int] = 24,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[OpenAIArticle]:
        """Get articles specifically categorized under OpenAI Engineering (https://openai.com/news/engineering/)."""
        criteria = OpenAIFilterCriteria(
            hours_back=hours_back,
            categories=[OpenAICategory.ENGINEERING.value],
            limit=limit,
        )
        return self.get_recent_articles(criteria=criteria, fetch_full_content=fetch_full_content)

    def get_focus_articles(
        self,
        hours_back: Optional[int] = 24,
        limit: Optional[int] = None,
        fetch_full_content: bool = False,
    ) -> List[OpenAIArticle]:
        """Get articles from the two primary focus areas: Research and Engineering combined."""
        criteria = OpenAIFilterCriteria(
            hours_back=hours_back,
            categories=[OpenAICategory.RESEARCH.value, OpenAICategory.ENGINEERING.value],
            limit=limit,
        )
        return self.get_recent_articles(criteria=criteria, fetch_full_content=fetch_full_content)


# ---------------------------------------------------------------------------
# Simple Top-Level Helper Functions
# ---------------------------------------------------------------------------
def get_daily_openai_articles(
    hours_back: int = 24,
    categories: Optional[List[str]] = None,
) -> List[OpenAIArticle]:
    """Retrieve articles published by OpenAI in the last N hours."""
    with OpenAIScraperService() as service:
        criteria = OpenAIFilterCriteria(hours_back=hours_back, categories=categories)
        return service.get_recent_articles(criteria=criteria)


def get_daily_openai_focus(hours_back: int = 24) -> List[OpenAIArticle]:
    """Retrieve articles from OpenAI's Research and Engineering sections in the last N hours."""
    with OpenAIScraperService() as service:
        return service.get_focus_articles(hours_back=hours_back)


def main() -> None:
    """CLI to inspect and filter OpenAI articles using OOP & Pydantic."""
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    parser = argparse.ArgumentParser(description="OpenAI News Scraper (OOP & Pydantic)")
    parser.add_argument(
        "--hours",
        "-H",
        type=int,
        default=24,
        help="Hours lookback window (default: 24). Set 0 to fetch all recent entries without time filter.",
    )
    parser.add_argument(
        "--category",
        "-c",
        type=str,
        action="append",
        help="Category to filter (e.g. 'Research', 'Engineering', 'Company', 'Safety'). Can be repeated.",
    )
    parser.add_argument(
        "--focus",
        "-f",
        action="store_true",
        help="Focus only on primary technical areas: Research and Engineering",
    )
    parser.add_argument(
        "--query",
        "-q",
        type=str,
        help="Keyword search in title or summary",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=None,
        help="Limit number of articles displayed",
    )
    parser.add_argument(
        "--fetch-content",
        "-C",
        action="store_true",
        help="Fetch full article content directly from original openai.com website",
    )
    parser.add_argument(
        "--markdown",
        "-m",
        action="store_true",
        help="Print matching articles in Markdown format directly to stdout",
    )

    args = parser.parse_args()

    hours = args.hours if args.hours > 0 else None
    target_categories = args.category

    if args.focus:
        target_categories = ["Research", "Engineering"]

    criteria = OpenAIFilterCriteria(
        hours_back=hours,
        categories=target_categories,
        search_query=args.query,
        limit=args.limit,
    )

    print("=" * 75)
    print("OPENAI NEWS & RESEARCH SCRAPER (OOP & PYDANTIC)")
    print("=" * 75)
    print(f"Feed URL:        {DEFAULT_OPENAI_RSS_URL}")
    print(f"Time Window:     Last {args.hours} hours" if hours else "Time Window:     All Available (no time filter)")
    print(f"Category Filter: {target_categories if target_categories else 'All Categories'}")
    if args.query:
        print(f"Search Query:    '{args.query}'")
    print("-" * 75)

    with OpenAIScraperService() as service:
        articles = service.get_recent_articles(criteria=criteria, fetch_full_content=args.fetch_content)

        if args.markdown:
            for art in articles:
                print(art.to_markdown())
                print("\n---\n")
        else:
            print(f"\nFound {len(articles)} matching OpenAI article(s):")
            print("=" * 75)

            for idx, art in enumerate(articles, 1):
                pub_str = art.published_at.strftime("%Y-%m-%d %H:%M:%S UTC")
                cat_badge = f"[{', '.join(art.categories)}]" if art.categories else "[General]"
                print(f"\n[{idx}] {cat_badge} {art.title}")
                print(f"    Published: {pub_str}")
                print(f"    URL:       {art.url}")
                if art.has_full_content and art.content:
                    word_cnt = art.word_count or len(art.content.split())
                    preview = art.content[:250].strip().replace("\n", " ")
                    print(f"    Full Text: [{word_cnt:,} words] \"{preview}...\"")
                elif art.summary:
                    print(f"    Summary:   \"{art.summary[:200]}...\"")

            print("\n" + "=" * 75)


if __name__ == "__main__":
    main()
