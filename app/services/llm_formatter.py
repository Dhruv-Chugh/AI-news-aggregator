"""LLM Markdown Formatter Service (OOP & Pydantic Architecture).

Formats scraped database entries across all 3 scrapers (YouTube, OpenAI, Anthropic)
into clean, simple, and token-efficient GitHub-Flavored Markdown optimized for passing
directly to Large Language Models (LLMs) for summarization and daily digest synthesis.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from app.database.models import Article
from app.database.repository import NewsRepository

logger = logging.getLogger("ai_news.llm_formatter")


class LLMMarkdownFormatter:
    """Service to format database articles and video transcripts into clean Markdown for LLMs."""

    def __init__(self) -> None:
        pass

    def format_article(self, article: Article, index: Optional[int] = None) -> str:
        """Format a single Article into clean, LLM-ready markdown containing metadata and whole content."""
        return article.to_llm_markdown(index=index)

    def format_articles(
        self,
        articles: List[Article],
        title: str = "Scraped Articles & Knowledge Feed for LLM Digest",
        include_overview_header: bool = True,
    ) -> str:
        """Format a list of articles into a single cohesive Markdown document ready for LLM consumption."""
        if not articles:
            return f"# {title}\n\n_No articles found matching the specified criteria._\n"

        parts: List[str] = []

        if include_overview_header:
            now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            total = len(articles)
            total_words = sum(a.word_count or 0 for a in articles)

            # Source count breakdown
            source_counts: Dict[str, int] = {}
            for a in articles:
                src_name = a.source.name if a.source else (a.category or "Unknown")
                source_counts[src_name] = source_counts.get(src_name, 0) + 1

            breakdown_str = ", ".join(f"{name}: {cnt}" for name, cnt in sorted(source_counts.items()))

            header = [
                f"# {title}",
                "",
                f"> **Total Items**: `{total}` | **Total Word Count**: `{total_words:,}` | **Generated**: `{now_str}`",
                f"> **Sources Breakdown**: {breakdown_str}",
                "",
                "---",
                "",
            ]
            parts.append("\n".join(header))

        article_blocks = [
            self.format_article(art, index=idx)
            for idx, art in enumerate(articles, 1)
        ]
        parts.append("\n\n---\n\n".join(article_blocks))
        parts.append("")

        return "\n".join(parts)

    def format_source_grouped(
        self,
        articles: List[Article],
        title: str = "Scraped Articles & Knowledge Feed for LLM Digest (Grouped by Source)",
    ) -> str:
        """Format articles grouped under source categories (e.g. OpenAI, Anthropic, YouTube)."""
        if not articles:
            return f"# {title}\n\n_No articles found matching the specified criteria._\n"

        # Group by source type
        grouped: Dict[str, List[Article]] = {}
        for art in articles:
            stype = art.source.source_type if art.source else "other"
            grouped.setdefault(stype, []).append(art)

        parts: List[str] = [
            f"# {title}",
            "",
            f"> **Total Items**: `{len(articles)}` | **Sources**: {', '.join(sorted(grouped.keys()))}",
            "",
            "---",
            "",
        ]

        # Display names for groups
        type_titles = {
            "openai": "OpenAI News & Research",
            "anthropic": "Anthropic Research & Engineering",
            "youtube": "YouTube Knowledge & Spoken Transcripts",
        }

        global_idx = 1
        for stype in sorted(grouped.keys()):
            group_articles = grouped[stype]
            group_label = type_titles.get(stype.lower(), f"{stype.title()} Content")
            parts.append(f"# 📦 {group_label} ({len(group_articles)} items)\n")

            blocks = []
            for art in group_articles:
                blocks.append(self.format_article(art, index=global_idx))
                global_idx += 1

            parts.append("\n\n---\n\n".join(blocks))
            parts.append("\n")

        return "\n".join(parts)

    def format_database_entries(
        self,
        repo: Optional[NewsRepository] = None,
        hours: Optional[int] = None,
        source_type: Optional[str] = None,
        unsummarized_only: bool = False,
        limit: int = 100,
        grouped: bool = False,
    ) -> str:
        """Query database and format all matching entries into LLM Markdown."""
        def _fetch(active_repo: NewsRepository) -> List[Article]:
            if unsummarized_only:
                return active_repo.articles.get_unsummarized(hours=hours, limit=limit)
            return active_repo.articles.get_recent(hours=hours, source_type=source_type, limit=limit)

        if repo is not None:
            articles = _fetch(repo)
            return self.format_source_grouped(articles) if grouped else self.format_articles(articles)

        with NewsRepository() as managed_repo:
            articles = _fetch(managed_repo)
            return self.format_source_grouped(articles) if grouped else self.format_articles(articles)


# ---------------------------------------------------------------------------
# Convenient top-level helper functions
# ---------------------------------------------------------------------------
def format_article_for_llm(article: Article, index: Optional[int] = None) -> str:
    """Format single article to LLM markdown."""
    return LLMMarkdownFormatter().format_article(article, index=index)


def format_articles_for_llm(
    articles: List[Article],
    title: str = "Scraped Articles & Knowledge Feed for LLM Digest",
) -> str:
    """Format list of articles to LLM markdown."""
    return LLMMarkdownFormatter().format_articles(articles, title=title)


def get_database_llm_markdown(
    hours: Optional[int] = None,
    source_type: Optional[str] = None,
    unsummarized_only: bool = False,
    limit: int = 100,
    grouped: bool = False,
) -> str:
    """Fetch database entries and return formatted LLM markdown."""
    return LLMMarkdownFormatter().format_database_entries(
        hours=hours,
        source_type=source_type,
        unsummarized_only=unsummarized_only,
        limit=limit,
        grouped=grouped,
    )


def main() -> None:
    """CLI to inspect or output formatted LLM Markdown directly from the terminal."""
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Format database scraped entries into clean Markdown for LLMs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--hours",
        "-H",
        type=int,
        default=None,
        help="Filter articles published in the last N hours (default: all entries)",
    )
    parser.add_argument(
        "--source",
        "-s",
        type=str,
        choices=["youtube", "openai", "anthropic"],
        default=None,
        help="Filter articles by source type",
    )
    parser.add_argument(
        "--unsummarized",
        "-u",
        action="store_true",
        help="Only include articles that have not yet been summarized",
    )
    parser.add_argument(
        "--limit",
        "-n",
        type=int,
        default=50,
        help="Maximum number of articles to include",
    )
    parser.add_argument(
        "--grouped",
        "-g",
        action="store_true",
        help="Group output by source type",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="Optional file path to write Markdown output to",
    )

    args = parser.parse_args()

    md_output = get_database_llm_markdown(
        hours=args.hours,
        source_type=args.source,
        unsummarized_only=args.unsummarized,
        limit=args.limit,
        grouped=args.grouped,
    )

    if args.output:
        p = Path(args.output)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(md_output, encoding="utf-8")
        print(f"✅ Successfully wrote LLM Markdown ({len(md_output):,} chars) to: {p.resolve()}")
    else:
        print(md_output)


if __name__ == "__main__":
    main()

