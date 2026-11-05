"""Simple Unified AI News Runner with Database Persistence.

Brings together:
1. YouTube (monitored channels from config/sources.json + transcripts, excluding Shorts)
2. OpenAI (news, research, engineering + full web content)
3. Anthropic (news, engineering, research + full web content)
4. PostgreSQL Database Persistence (deduplication + metadata storage)

Quick CLI Usage:
    python -m app.scrapers.runner                # Run for last 24h & sync to DB (default)
    python -m app.scrapers.runner 48             # Run for last 48 hours
    python -m app.scrapers.runner --all          # Run for all available history
    python -m app.scrapers.runner --no-db        # Run without saving to database
    python -m app.scrapers.runner --clean-shorts # Remove all YouTube Shorts from database
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
from app.database.repository import NewsRepository
from app.database.session import check_connection
from app.models.anthropic import AnthropicArticle
from app.models.openai import OpenAIArticle, OpenAIFilterCriteria
from app.models.youtube import FilterCriteria, YouTubeVideo
from app.scrapers.anthropic import AnthropicScraperService
from app.scrapers.openai import OpenAIScraperService
from app.scrapers.youtube import YouTubeService

logger = logging.getLogger("ai_news.runner")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class AggregationResult(BaseModel):
    """Container holding collected items, counts, and database sync details."""

    executed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS
    cutoff_time: Optional[datetime] = None
    youtube_videos: List[YouTubeVideo] = Field(default_factory=list)
    openai_articles: List[OpenAIArticle] = Field(default_factory=list)
    anthropic_articles: List[AnthropicArticle] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # Database sync results
    db_synced: bool = False
    db_items_saved: int = 0
    db_new_items: int = 0
    db_updated_items: int = 0
    cleaned_shorts: int = 0

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
        print(f"  • YouTube Videos:     {c['youtube']} (Shorts excluded)")
        print(f"  • OpenAI Articles:    {c['openai']}")
        print(f"  • Anthropic Articles: {c['anthropic']}")
        print("  " + "-" * 40)
        print(f"  • Total Items:        {c['total']}")

        if self.db_synced:
            print(f"  • Database Sync:      ✅ Saved {self.db_items_saved} items ({self.db_new_items} new, {self.db_updated_items} updated)")
        else:
            print("  • Database Sync:      ⚪ Not synced (DB offline or skipped)")

        if self.cleaned_shorts > 0:
            print(f"  • Shorts Removed:     🗑️ {self.cleaned_shorts} short(s) cleaned from DB")

        if self.warnings:
            print("\n⚠️ Warnings:")
            for w in self.warnings:
                print(f"  - {w}")
        print("=" * 60 + "\n")


class AggregationRunner:
    """Unified runner coordinating data ingestion and database persistence across all sources."""

    def __init__(
        self,
        sources_config: Optional[SourcesConfig] = None,
        db_repo: Optional[NewsRepository] = None,
    ) -> None:
        self.sources_config = sources_config or get_sources_config()
        self.db_repo = db_repo

    def __enter__(self) -> AggregationRunner:
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        pass

    def sync_to_database(
        self,
        videos: List[YouTubeVideo],
        openai_articles: List[OpenAIArticle],
        anthropic_articles: List[AnthropicArticle],
        repo: Optional[NewsRepository] = None,
    ) -> Dict[str, Any]:
        """Save scraped items and rich metadata to the database with deduplication, excluding Shorts."""
        stats: Dict[str, Any] = {
            "synced": False,
            "saved": 0,
            "new": 0,
            "updated": 0,
            "cleaned_shorts": 0,
        }

        def _persist(active_repo: NewsRepository) -> None:
            # 1. Clean any existing shorts in the database
            removed_shorts = active_repo.remove_shorts()
            stats["cleaned_shorts"] = removed_shorts
            if removed_shorts > 0:
                logger.info("Cleaned %d YouTube Short(s) from database during sync", removed_shorts)

            # 2. Persist YouTube videos (Shorts are refused by save_youtube_video)
            for v in videos:
                if v.is_short:
                    continue
                _, is_new = active_repo.save_youtube_video(v)
                stats["saved"] += 1
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1

            # 3. Persist OpenAI articles
            for oai in openai_articles:
                _, is_new = active_repo.save_openai_article(oai)
                stats["saved"] += 1
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1

            # 4. Persist Anthropic articles
            for ant in anthropic_articles:
                _, is_new = active_repo.save_anthropic_article(ant)
                stats["saved"] += 1
                if is_new:
                    stats["new"] += 1
                else:
                    stats["updated"] += 1

            stats["synced"] = True

        if repo is not None:
            _persist(repo)
        elif self.db_repo is not None:
            _persist(self.db_repo)
        else:
            if not check_connection():
                logger.info(
                    "Database offline: Scraped items not persisted. "
                    "Start PostgreSQL with 'docker compose up -d' to enable database persistence."
                )
                stats["offline"] = True
                return stats

            try:
                with NewsRepository() as managed_repo:
                    _persist(managed_repo)
            except Exception as e:
                logger.error("Failed to sync items to database: %s", e)
                stats["error"] = str(e)

        return stats

    def run(
        self,
        hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS,
        hours: Optional[int] = None,
        include_youtube: bool = True,
        include_openai: bool = True,
        include_anthropic: bool = True,
        fetch_transcripts: bool = True,
        fetch_full_content: bool = True,
        sync_to_db: bool = True,
        db_repo: Optional[NewsRepository] = None,
    ) -> AggregationResult:
        """Execute unified ingestion across active sources and sync to database."""
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

        # 1. YouTube Channels (excluding Shorts)
        if include_youtube:
            channels = self.sources_config.get_active_youtube_channels()
            if not channels:
                warnings.append("YouTube: No active channels found in config/sources.json")
            else:
                try:
                    logger.info("Scraping %d active YouTube channel(s) (Shorts excluded)...", len(channels))
                    with YouTubeService(channels=channels) as yt:
                        crit = FilterCriteria(hours_back=actual_hours, include_shorts=False)
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

        # 4. Sync to Database
        db_synced = False
        db_items_saved = 0
        db_new_items = 0
        db_updated_items = 0
        cleaned_shorts = 0

        if sync_to_db:
            logger.info("Syncing scraped articles, transcripts, and metadata to database...")
            db_stats = self.sync_to_database(
                videos=videos,
                openai_articles=openai_articles,
                anthropic_articles=anthropic_articles,
                repo=db_repo,
            )
            db_synced = db_stats.get("synced", False)
            db_items_saved = db_stats.get("saved", 0)
            db_new_items = db_stats.get("new", 0)
            db_updated_items = db_stats.get("updated", 0)
            cleaned_shorts = db_stats.get("cleaned_shorts", 0)
            if "error" in db_stats:
                warnings.append(f"Database sync warning: {db_stats['error']}")

        return AggregationResult(
            executed_at=datetime.now(timezone.utc),
            hours_back=actual_hours,
            cutoff_time=cutoff,
            youtube_videos=videos,
            openai_articles=openai_articles,
            anthropic_articles=anthropic_articles,
            warnings=warnings,
            db_synced=db_synced,
            db_items_saved=db_items_saved,
            db_new_items=db_new_items,
            db_updated_items=db_updated_items,
            cleaned_shorts=cleaned_shorts,
        )


def run_news_aggregation(
    hours_back: Optional[int] = DEFAULT_LOOKBACK_HOURS,
    hours: Optional[int] = None,
    include_youtube: bool = True,
    include_openai: bool = True,
    include_anthropic: bool = True,
    fetch_transcripts: bool = True,
    fetch_full_content: bool = True,
    sync_to_db: bool = True,
    db_repo: Optional[NewsRepository] = None,
) -> AggregationResult:
    """Streamlined function to run the complete pipeline in one call."""
    effective_hours = hours if hours is not None else hours_back
    with AggregationRunner(db_repo=db_repo) as runner:
        return runner.run(
            hours_back=effective_hours,
            include_youtube=include_youtube,
            include_openai=include_openai,
            include_anthropic=include_anthropic,
            fetch_transcripts=fetch_transcripts,
            fetch_full_content=fetch_full_content,
            sync_to_db=sync_to_db,
            db_repo=db_repo,
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
        "--clean-shorts",
        action="store_true",
        help="Scan and delete all YouTube Shorts from the database",
    )
    parser.add_argument(
        "--llm-markdown",
        action="store_true",
        help="Export database entries formatted as clean Markdown for LLMs",
    )
    parser.add_argument("--no-db", action="store_true", help="Skip saving scraped items to database")
    parser.add_argument("--no-yt", action="store_true", help="Skip YouTube")
    parser.add_argument("--no-openai", action="store_true", help="Skip OpenAI")
    parser.add_argument("--no-anthropic", action="store_true", help="Skip Anthropic")
    parser.add_argument("--no-transcripts", action="store_true", help="Skip video transcripts")
    parser.add_argument("--no-content", action="store_true", help="Skip full web article text")

    args = parser.parse_args()

    cfg = get_sources_config()

    # 0. Output LLM Markdown on demand
    if args.llm_markdown:
        if not check_connection():
            print("❌ Database is not reachable. (Run 'docker compose up -d' first)\n")
            return
        from app.services.llm_formatter import get_database_llm_markdown

        hours_val = None if args.all else (args.hours if args.hours > 0 else None)
        print(get_database_llm_markdown(hours=hours_val))
        return

    # 1. Clean shorts on demand
    if args.clean_shorts:
        print("\n🧹 Scanning and removing YouTube Shorts from database...")
        if not check_connection():
            print("❌ Database is not reachable. (Run 'docker compose up -d' first)\n")
            return
        with NewsRepository() as repo:
            removed = repo.remove_shorts()
            print(f"✅ Finished! Removed {removed} YouTube Short(s) from database.\n")
        return

    # 2. List channels
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

    # 3. Add channel effortlessly
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
        sync_to_db=not args.no_db,
    )
    result.print_summary()


if __name__ == "__main__":
    main()
