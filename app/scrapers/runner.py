"""Simple Unified AI News Runner.

Brings together:
1. YouTube (monitored channels from config/sources.json + transcripts)
2. OpenAI (news, research, engineering + full web content)
3. Anthropic (news, engineering, research + full web content)

Quick CLI Usage:
    python -m app.scrapers.runner                # Run for last 24 hours (default)
    python -m app.scrapers.runner 48             # Run for last 48 hours
    python -m app.scrapers.runner --all          # Run for all available history
    python -m app.scrapers.runner --channels     # View monitored YouTube channels
    python -m app.scrapers.runner --add @handle  # Add a new channel effortlessly!
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.config import (
    DEFAULT_LOOKBACK_HOURS,
    SourcesConfig,
    add_channel,
    get_sources_config,
)
from app.models.anthropic import AnthropicArticle
from app.models.openai import OpenAIArticle, OpenAIFilterCriteria
from app.models.youtube import FilterCriteria, YouTubeVideo
from app.scrapers.anthropic import AnthropicScraperService
from app.scrapers.openai import OpenAIScraperService
from app.scrapers.youtube import YouTubeService
from app.services.markdown_exporter import MarkdownExporter

logger = logging.getLogger("ai_news.runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class AggregationResult(BaseModel):
    """Container holding collected items, counts, and exported file details."""

    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS
    cutoff_time: Optional[datetime] = None
    youtube_videos: List[YouTubeVideo] = Field(default_factory=list)
    openai_articles: List[OpenAIArticle] = Field(default_factory=list)
    anthropic_articles: List[AnthropicArticle] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    markdown_digest: Optional[str] = None
    export_path: Optional[str] = None

    @property
    def total_items(self) -> int:
        return len(self.youtube_videos) + len(self.openai_articles) + len(self.anthropic_articles)

    @property
    def summary_counts(self) -> Dict[str, int]:
        return {
            "youtube": len(self.youtube_videos),
            "openai": len(self.openai_articles),
            "anthropic": len(self.anthropic_articles),
            "total": self.total_items,
        }

    @property
    def has_items(self) -> bool:
        return self.total_items > 0

    def print_summary(self) -> None:
        """Display clean terminal summary."""
        c = self.summary_counts
        time_desc = f"last {self.hours_back} hours" if self.hours_back else "all available history"
        print("\n" + "=" * 60)
        print(f"📊 AGGREGATION RESULTS ({time_desc})")
        print("=" * 60)
        print(f"  • YouTube Videos:     {c['youtube']}")
        print(f"  • OpenAI Articles:    {c['openai']}")
        print(f"  • Anthropic Articles: {c['anthropic']}")
        print("  " + "-" * 40)
        print(f"  • Total Items:        {c['total']}")
        if self.export_path:
            print(f"  • Exported Digest:    {self.export_path}")
        if self.warnings:
            print("\n⚠️ Warnings:")
            for w in self.warnings:
                print(f"  - {w}")
        print("=" * 60 + "\n")


class AggregationRunner:
    """Unified runner coordinating data ingestion across all sources."""

    def __init__(self, sources_config: Optional[SourcesConfig] = None) -> None:
        self.sources_config = sources_config or get_sources_config()
        self.exporter = MarkdownExporter()

    def __enter__(self) -> AggregationRunner:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def run(
        self,
        hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS,
        hours: Optional[int] = None,
        include_youtube: bool = True,
        include_openai: bool = True,
        include_anthropic: bool = True,
        fetch_transcripts: bool = True,
        fetch_full_content: bool = True,
        export_markdown: bool = True,
        export_path: Optional[str] = None,
    ) -> AggregationResult:
        """Execute unified ingestion across active sources."""
        eff_hours = hours if hours is not None else hours_back
        actual_hours = eff_hours if (eff_hours and eff_hours > 0) else None
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=actual_hours)
            if actual_hours
            else None
        )

        videos: List[YouTubeVideo] = []
        openai_articles: List[OpenAIArticle] = []
        anthropic_articles: List[AnthropicArticle] = []
        warnings: List[str] = []

        # 1. YouTube Channels
        if include_youtube:
            channels = self.sources_config.get_active_youtube_channels()
            if not channels:
                warnings.append("YouTube: No active channels found in config/sources.json")
            else:
                try:
                    logger.info("Scraping %d active YouTube channel(s)...", len(channels))
                    with YouTubeService(channels=channels) as yt:
                        crit = FilterCriteria(hours_back=actual_hours)
                        videos = yt.get_recent_videos(criteria=crit, fetch_transcripts=fetch_transcripts)
                except Exception as e:
                    msg = f"YouTube aggregation failed: {e}"
                    logger.error(msg)
                    warnings.append(msg)

        # 2. OpenAI News & Research
        if include_openai and self.sources_config.openai.is_active:
            try:
                logger.info("Scraping OpenAI RSS feed...")
                with OpenAIScraperService(feed_url=self.sources_config.openai.rss_url) as oai:
                    crit = OpenAIFilterCriteria(hours_back=actual_hours)
                    openai_articles = oai.get_recent_articles(criteria=crit, fetch_full_content=fetch_full_content)
            except Exception as e:
                msg = f"OpenAI aggregation failed: {e}"
                logger.error(msg)
                warnings.append(msg)

        # 3. Anthropic News, Engineering & Research
        if include_anthropic and self.sources_config.anthropic.is_active:
            try:
                logger.info("Scraping Anthropic RSS feeds...")
                with AnthropicScraperService(feeds=self.sources_config.anthropic.feeds) as ant:
                    anthropic_articles = ant.get_articles(hours_back=actual_hours, fetch_full_content=fetch_full_content)
            except Exception as e:
                msg = f"Anthropic aggregation failed: {e}"
                logger.error(msg)
                warnings.append(msg)

        # 4. Export Markdown Digest
        digest_md: Optional[str] = None
        saved_file: Optional[str] = None

        if export_markdown:
            date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            default_dest = export_path or f"exports/daily_digest_{date_str}.md"
            title_suffix = f" (Past {actual_hours}h)" if actual_hours else " (All History)"

            digest_md = self.exporter.export_unified_digest(
                openai_articles=openai_articles,
                anthropic_articles=anthropic_articles,
                videos=videos,
                title=f"AI News Aggregator Digest{title_suffix}",
                include_full_content=fetch_full_content,
            )

            try:
                p = self.exporter.save_to_file(digest_md, default_dest)
                saved_file = str(p)
            except Exception as e:
                logger.error("Failed to save markdown digest: %s", e)
                warnings.append(f"Markdown export failed: {e}")

        return AggregationResult(
            executed_at=datetime.now(timezone.utc),
            hours_back=actual_hours,
            cutoff_time=cutoff,
            youtube_videos=videos,
            openai_articles=openai_articles,
            anthropic_articles=anthropic_articles,
            warnings=warnings,
            markdown_digest=digest_md,
            export_path=saved_file,
        )


def run_news_aggregation(
    hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS,
    hours: Optional[int] = None,
    include_youtube: bool = True,
    include_openai: bool = True,
    include_anthropic: bool = True,
    fetch_transcripts: bool = True,
    fetch_full_content: bool = True,
    export_markdown: bool = True,
    export_path: Optional[str] = None,
) -> AggregationResult:
    """Streamlined function to run the complete pipeline in one call."""
    effective_hours = hours if hours is not None else hours_back
    with AggregationRunner() as runner:
        return runner.run(
            hours_back=effective_hours,
            include_youtube=include_youtube,
            include_openai=include_openai,
            include_anthropic=include_anthropic,
            fetch_transcripts=fetch_transcripts,
            fetch_full_content=fetch_full_content,
            export_markdown=export_markdown,
            export_path=export_path,
        )


# Super-simple alias
run = run_news_aggregation


def main() -> None:
    """CLI for the unified AI news runner."""
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(
        description="Simple Unified AI News Aggregator Runner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "hours",
        nargs="?",
        type=int,
        default=DEFAULT_LOOKBACK_HOURS,
        help="Hours lookback window (e.g. 24, 48). Set 0 for all available history.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Run for all available history (disables time filter)",
    )
    parser.add_argument(
        "--channels",
        action="store_true",
        help="List all currently monitored YouTube channels",
    )
    parser.add_argument(
        "--add",
        type=str,
        metavar="IDENTIFIER",
        help="Add a channel effortlessly by handle (e.g. --add @TwoMinutePapers) or URL",
    )
    parser.add_argument(
        "--export-md",
        type=str,
        default=None,
        help="Save digest markdown to specified file path",
    )
    parser.add_argument("--no-yt", action="store_true", help="Skip YouTube")
    parser.add_argument("--no-openai", action="store_true", help="Skip OpenAI")
    parser.add_argument("--no-anthropic", action="store_true", help="Skip Anthropic")
    parser.add_argument("--no-transcripts", action="store_true", help="Skip video transcripts")
    parser.add_argument("--no-content", action="store_true", help="Skip full web article text")

    args = parser.parse_args()

    cfg = get_sources_config()

    # 1. List channels
    if args.channels:
        print(f"\n📺 Monitored YouTube Channels ({len(cfg.youtube_channels)}):")
        print("=" * 60)
        for idx, ch in enumerate(cfg.youtube_channels, 1):
            status = "🟢 Active" if ch.is_active else "🔴 Inactive"
            handle_str = f" ({ch.handle})" if ch.handle else ""
            print(f"{idx}. {ch.name}{handle_str} [{status}]")
            print(f"   ID:   {ch.channel_id}")
            print(f"   Feed: {ch.feed_url}")
        print()
        return

    # 2. Add channel effortlessly
    if args.add:
        print(f"\n🔍 Resolving and adding YouTube channel '{args.add}'...")
        try:
            ch = add_channel(args.add)
            print(f"✅ Successfully added '{ch.name}' ({ch.channel_id}) to config/sources.json!\n")
        except Exception as e:
            print(f"❌ Could not add channel '{args.add}': {e}\n")
        return

    hours_to_use = 0 if args.all else args.hours

    print(f"\n🚀 Running AI News Aggregator ({'All history' if hours_to_use == 0 else f'Last {hours_to_use} hours'})...")
    result = run(
        hours=hours_to_use,
        include_youtube=not args.no_yt,
        include_openai=not args.no_openai,
        include_anthropic=not args.no_anthropic,
        fetch_transcripts=not args.no_transcripts,
        fetch_full_content=not args.no_content,
        export_path=args.export_md,
    )
    result.print_summary()


if __name__ == "__main__":
    main()
