"""Pydantic data models for YouTube channel, video, and transcript surfaces."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
import re

from pydantic import BaseModel, Field, field_validator


class ChannelConfig(BaseModel):
    """Pydantic model representing a tracked YouTube channel."""

    name: str = Field(..., description="Human-readable channel display name")
    channel_id: str = Field(..., description="24-character YouTube Channel ID starting with UC")
    handle: Optional[str] = Field(default=None, description="Creator handle starting with @")
    url: Optional[str] = Field(default=None, description="Direct channel URL")
    is_active: bool = Field(default=True, description="Whether channel is active for aggregation")

    @field_validator("channel_id")
    @classmethod
    def validate_channel_id(cls, v: str) -> str:
        clean = v.strip()
        if not re.fullmatch(r"UC[a-zA-Z0-9_-]{22}", clean):
            raise ValueError(f"Invalid YouTube channel_id format: '{clean}'. Must start with 'UC' and be 24 chars.")
        return clean

    @property
    def feed_url(self) -> str:
        """Construct the official YouTube RSS feed URL."""
        return f"https://www.youtube.com/feeds/videos.xml?channel_id={self.channel_id}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return self.model_dump()


class TranscriptSnippet(BaseModel):
    """Timestamped snippet of spoken audio."""

    start: float = Field(..., description="Start timestamp in seconds")
    duration: float = Field(..., description="Duration in seconds")
    text: str = Field(..., description="Transcribed spoken words")


class VideoTranscript(BaseModel):
    """Pydantic model representing structured video transcript knowledge."""

    video_id: str = Field(..., description="11-character YouTube video ID")
    available: bool = Field(default=False, description="Whether transcript extraction succeeded")
    text: str = Field(default="", description="Full clean aggregated transcript text")
    language: Optional[str] = Field(default=None, description="Language name (e.g. English (auto-generated))")
    language_code: Optional[str] = Field(default=None, description="Language ISO code (e.g. en, hi)")
    is_generated: bool = Field(default=False, description="True if automatic speech recognition (ASR)")
    word_count: int = Field(default=0, description="Total word count")
    character_count: int = Field(default=0, description="Total character count")
    error_reason: Optional[str] = Field(default=None, description="Detailed error message if unavailable")
    snippets: List[TranscriptSnippet] = Field(default_factory=list, description="Raw timestamped snippets")

    @property
    def has_content(self) -> bool:
        """Check if transcript has actual readable text."""
        return self.available and len(self.text.strip()) > 0


class YouTubeVideo(BaseModel):
    """Pydantic model representing a discovered YouTube video."""

    video_id: str = Field(..., description="Unique 11-character YouTube video ID")
    title: str = Field(..., description="Video title")
    url: str = Field(..., description="Direct YouTube watch URL")
    channel_id: str = Field(..., description="Parent YouTube channel ID")
    channel_name: str = Field(..., description="Parent channel title/display name")
    published_at: datetime = Field(..., description="Publication timestamp in UTC")
    updated_at: Optional[datetime] = Field(default=None, description="Last updated timestamp in UTC")
    description: str = Field(default="", description="Video description text from RSS/webpage")
    thumbnail_url: Optional[str] = Field(default=None, description="Video thumbnail image URL")
    transcript: Optional[VideoTranscript] = Field(default=None, description="Associated transcript knowledge")

    @field_validator("published_at", mode="before")
    @classmethod
    def ensure_utc_timezone(cls, v: Any) -> datetime:
        """Ensure publication datetime has UTC timezone."""
        if isinstance(v, datetime):
            return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
        return v

    @property
    def is_short(self) -> bool:
        """Determine if video is a YouTube Short based on URL."""
        return "/shorts/" in self.url

    @property
    def has_transcript(self) -> bool:
        """Check if video has an available transcript."""
        return self.transcript is not None and self.transcript.available


class FilterCriteria(BaseModel):
    """Pydantic model for filtering YouTube videos by time and attributes."""

    hours_back: Optional[int] = Field(default=24, description="Lookback window in hours (default 24h)")
    since: Optional[datetime] = Field(default=None, description="Explicit cutoff timestamp in UTC")
    max_results_per_channel: Optional[int] = Field(default=None, description="Max videos to retain per channel")
    include_shorts: bool = Field(default=True, description="Whether to include YouTube Shorts")

    @property
    def cutoff_datetime(self) -> Optional[datetime]:
        """Compute the effective UTC datetime cutoff."""
        if self.since is not None:
            return self.since if self.since.tzinfo else self.since.replace(tzinfo=timezone.utc)
        if self.hours_back is not None and self.hours_back > 0:
            return datetime.now(timezone.utc) - timedelta(hours=self.hours_back)
        return None

