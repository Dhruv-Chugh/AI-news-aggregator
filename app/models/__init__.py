"""Pydantic data schemas for AI News Aggregator."""

from app.models.youtube import (
    ChannelConfig,
    FilterCriteria,
    TranscriptSnippet,
    VideoTranscript,
    YouTubeVideo,
)

__all__ = [
    "ChannelConfig",
    "FilterCriteria",
    "TranscriptSnippet",
    "VideoTranscript",
    "YouTubeVideo",
]

