"""YouTube Scraper Service.

Simple and lightweight service to discover YouTube videos via native RSS feeds.
Takes an easy list of channel names & IDs, fetches their latest videos,
and filters by publication time (e.g., last 24 hours).

For converting video audio/knowledge into text, it integrates with
`app.services.transcript_service.TranscriptService`.
"""

from __future__ import annotations

import argparse
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Union

import dateutil.parser
import feedparser
import httpx
from pydantic import BaseModel, Field

from app.services.transcript_service import TranscriptService, VideoTranscript

logger = logging.getLogger("ai_news.youtube")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

# ---------------------------------------------------------------------------
# Simple Channel Input List: Just add channel Name and ID (or Handle)
# ---------------------------------------------------------------------------
DEFAULT_CHANNELS: List[Dict[str, str]] = [
    {
        "name": "Think School",
        "id": "UCKZozRVHRYsYHGEyNKuhhdA",
        "handle": "@thinkschool",
    },
    {
        "name": "Figuring Out by Raj Shamani",
        "id": "UCzwCEE_PchiBULMnAJqhGVg",
        "handle": "@rajshamani",
    },
]


class YouTubeVideo(BaseModel):
    """Clean representation of a discovered YouTube video."""

    video_id: str
    title: str
    url: str
    channel_id: str
    channel_name: str
    published_at: datetime
    description: str = ""
    thumbnail_url: Optional[str] = None
    transcript: Optional[VideoTranscript] = None

    @property
    def has_transcript(self) -> bool:
        return self.transcript is not None and self.transcript.available

    def fetch_transcript(self) -> VideoTranscript:
        """Fetch and attach the full spoken transcript using TranscriptService."""
        service = TranscriptService()
        self.transcript = service.get_transcript(self.video_id)
        return self.transcript


class YouTubeService:
    """Service to discover and filter YouTube videos via RSS feeds."""

    RSS_FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

    def __init__(
        self,
        channels: Optional[List[Dict[str, str]]] = None,
        timeout: float = 15.0,
    ) -> None:
        """Initialize with an easy list of channels.

        Each channel can be a dict: {'name': 'Two Minute Papers', 'id': 'UC...'}
        or a list of channel ID / handle strings.
        """
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
        self.channels: List[Dict[str, str]] = []
        self._cache_handles: Dict[str, str] = {}

        # Pre-seed cache from defaults
        for ch in DEFAULT_CHANNELS:
            cid = ch["id"]
            self._cache_handles[cid.lower()] = cid
            if "handle" in ch:
                self._cache_handles[ch["handle"].lower()] = cid

        if channels is not None:
            for ch in channels:
                self.add_channel(ch)
        else:
            self.channels = list(DEFAULT_CHANNELS)

    def close(self) -> None:
        self.client.close()

    def __enter__(self) -> "YouTubeService":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()

    def resolve_channel_id(self, identifier: str) -> str:
        """Extract or resolve 24-char channel ID from ID, handle, or URL."""
        cleaned = identifier.strip()

        # Cache check
        if cleaned.lower() in self._cache_handles:
            return self._cache_handles[cleaned.lower()]

        # Direct UC ID
        if re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", cleaned):
            self._cache_handles[cleaned.lower()] = cleaned
            return cleaned

        # Channel URL
        m = re.search(r"/channel/(UC[a-zA-Z0-9_-]{22})", cleaned)
        if m:
            cid = m.group(1)
            self._cache_handles[cleaned.lower()] = cid
            return cid

        # Handle (@creator)
        handle = cleaned if cleaned.startswith("@") or cleaned.startswith("http") else f"@{cleaned}"
        url = handle if handle.startswith("http") else f"https://www.youtube.com/{handle}"

        try:
            logger.info("Resolving channel handle: %s", url)
            r = self.client.get(url)
            r.raise_for_status()

            patterns = [
                r'<link rel="canonical" href="https://www.youtube.com/channel/(UC[a-zA-Z0-9_-]{22})"',
                r'"externalId":"(UC[a-zA-Z0-9_-]{22})"',
                r'itemprop="channelId" content="(UC[a-zA-Z0-9_-]{22})"',
                r'"browseId":"(UC[a-zA-Z0-9_-]{22})"',
            ]
            for pat in patterns:
                found = re.search(pat, r.text)
                if found:
                    cid = found.group(1)
                    self._cache_handles[cleaned.lower()] = cid
                    return cid
        except Exception as e:
            logger.warning("Could not resolve handle %s: %s", identifier, e)

        raise ValueError(f"Could not resolve a valid channel ID for: '{identifier}'")

    def add_channel(self, channel: Union[str, Dict[str, str]]) -> Dict[str, str]:
        """Easy helper to add a channel by name and ID."""
        if isinstance(channel, str):
            cid = self.resolve_channel_id(channel)
            record = {"name": f"Channel {cid}", "id": cid}
        elif isinstance(channel, dict):
            raw_id = channel.get("id") or channel.get("channel_id") or channel.get("handle")
            if not raw_id:
                raise ValueError("Channel dict must have 'id' or 'handle' key")
            cid = self.resolve_channel_id(raw_id)
            name = channel.get("name") or f"Channel {cid}"
            record = {"name": name, "id": cid}
        else:
            raise TypeError("Channel must be a string or a dict")

        # Avoid duplicates
        if not any(c["id"] == record["id"] for c in self.channels):
            self.channels.append(record)

        return record

    def fetch_channel_videos(self, channel_id: str, channel_name: Optional[str] = None) -> List[YouTubeVideo]:
        """Fetch all recent videos for a channel from YouTube RSS."""
        feed_url = self.RSS_FEED_URL.format(channel_id=channel_id)
        name = channel_name or channel_id

        try:
            r = self.client.get(feed_url)
            if r.status_code == 200:
                feed = feedparser.parse(r.content)
            else:
                feed = feedparser.parse(feed_url)
        except Exception as e:
            logger.error("Error reading RSS feed for %s: %s", name, e)
            return []

        if feed.bozo and not feed.entries:
            return []

        videos: List[YouTubeVideo] = []
        detected_name = feed.feed.get("title") or name

        for entry in feed.entries:
            try:
                vid = getattr(entry, "yt_videoid", None)
                if not vid:
                    entry_id = entry.get("id", "")
                    if "yt:video:" in entry_id:
                        vid = entry_id.split("yt:video:")[-1]
                    elif "watch?v=" in entry.get("link", ""):
                        vid = entry.link.split("watch?v=")[-1].split("&")[0]

                if not vid:
                    continue

                title = entry.get("title", "Untitled Video").strip()
                link = entry.get("link", f"https://www.youtube.com/watch?v={vid}")

                # Date parsing
                pub_raw = entry.get("published") or entry.get("updated")
                if pub_raw:
                    pub_dt = dateutil.parser.parse(pub_raw)
                    if pub_dt.tzinfo is None:
                        pub_dt = pub_dt.replace(tzinfo=timezone.utc)
                    else:
                        pub_dt = pub_dt.astimezone(timezone.utc)
                else:
                    pub_dt = datetime.now(timezone.utc)

                # Description
                description = entry.get("summary") or entry.get("media_description") or ""

                # Thumbnail
                thumb = None
                if "media_thumbnail" in entry and len(entry.media_thumbnail) > 0:
                    thumb = entry.media_thumbnail[0].get("url")

                videos.append(
                    YouTubeVideo(
                        video_id=vid,
                        title=title,
                        url=link,
                        channel_id=channel_id,
                        channel_name=detected_name,
                        published_at=pub_dt,
                        description=description,
                        thumbnail_url=thumb,
                    )
                )
            except Exception as e:
                logger.warning("Error parsing entry: %s", e)

        return videos

    def get_latest_video(self, channel_id_or_handle: str) -> Optional[YouTubeVideo]:
        """Fetch the single latest video published by a channel."""
        cid = self.resolve_channel_id(channel_id_or_handle)
        videos = self.fetch_channel_videos(cid)
        return videos[0] if videos else None

    def filter_by_time(
        self,
        videos: List[YouTubeVideo],
        hours_back: Optional[int] = 24,
    ) -> List[YouTubeVideo]:
        """Filter videos published within the last N hours."""
        if hours_back is None or hours_back <= 0:
            return videos

        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours_back)
        return [v for v in videos if v.published_at >= cutoff]

    def get_recent_videos(
        self,
        hours_back: Optional[int] = 24,
        fetch_transcripts: bool = False,
    ) -> List[YouTubeVideo]:
        """Fetch and filter recent videos across all configured channels."""
        results: List[YouTubeVideo] = []

        for ch in self.channels:
            cid = ch["id"]
            name = ch.get("name")
            videos = self.fetch_channel_videos(cid, channel_name=name)
            filtered = self.filter_by_time(videos, hours_back=hours_back)

            if fetch_transcripts:
                for v in filtered:
                    v.fetch_transcript()

            results.extend(filtered)

        # Sort newest first
        results.sort(key=lambda x: x.published_at, reverse=True)
        return results


# ---------------------------------------------------------------------------
# Simple Top-Level Helper Functions
# ---------------------------------------------------------------------------
def get_channel_latest(channel_id_or_handle: str) -> Optional[YouTubeVideo]:
    """Get the latest video for a channel."""
    with YouTubeService() as svc:
        return svc.get_latest_video(channel_id_or_handle)


def get_daily_ai_videos(hours_back: int = 24, fetch_transcripts: bool = False) -> List[YouTubeVideo]:
    """Get all videos published across all configured channels in the last 24 hours."""
    with YouTubeService() as svc:
        return svc.get_recent_videos(hours_back=hours_back, fetch_transcripts=fetch_transcripts)


def main() -> None:
    """CLI to inspect channels and latest videos."""
    parser = argparse.ArgumentParser(description="YouTube AI News Ingestion")
    parser.add_argument(
        "--channel",
        "-c",
        type=str,
        help="Optional channel ID or handle. If omitted, checks all default channels.",
    )
    parser.add_argument(
        "--hours",
        "-H",
        type=int,
        default=24,
        help="Hours lookback (default 24). Set 0 for all latest videos.",
    )
    parser.add_argument(
        "--transcripts",
        action="store_true",
        help="Also fetch spoken transcripts for matching videos using TranscriptService",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("AI NEWS - YOUTUBE FEED DISCOVERY")
    print("=" * 70)

    channels = [{"id": args.channel, "name": args.channel}] if args.channel else None

    with YouTubeService(channels=channels) as svc:
        print(f"Monitoring {len(svc.channels)} Channel(s):")
        for ch in svc.channels:
            print(f"  • {ch.get('name', 'Channel')} ({ch['id']})")
        print("-" * 70)

        hours = args.hours if args.hours > 0 else None
        print(f"Filter: Published in the last {args.hours} hours" if hours else "Filter: Latest videos")
        print(f"Fetch Transcripts: {args.transcripts}\n")

        videos = svc.get_recent_videos(hours_back=hours, fetch_transcripts=args.transcripts)

        print(f"Found {len(videos)} video(s):")
        print("=" * 70)

        for i, v in enumerate(videos, 1):
            pub = v.published_at.strftime("%Y-%m-%d %H:%M:%S UTC")
            print(f"\n[{i}] {v.title}")
            print(f"    Channel:   {v.channel_name} ({v.channel_id})")
            print(f"    Published: {pub}")
            print(f"    URL:       {v.url}")

            if v.transcript:
                if v.transcript.available:
                    print(f"    Transcript: {v.transcript.word_count:,} words ({v.transcript.language})")
                    print(f"    Preview:    \"{v.transcript.text[:200]}...\"")
                else:
                    print(f"    Transcript: {v.transcript.error}")

    print("\n" + "=" * 70)


if __name__ == "__main__":
    main()
