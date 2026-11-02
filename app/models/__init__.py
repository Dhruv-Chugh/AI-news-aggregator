"""Pydantic data schemas for AI News Aggregator."""

from app.models.anthropic import (
    AnthropicArticle,
    AnthropicCategory,
    AnthropicFilterCriteria,
)
from app.models.openai import (
    OpenAIArticle,
    OpenAICategory,
    OpenAIFilterCriteria,
)
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
    "OpenAIArticle",
    "OpenAICategory",
    "OpenAIFilterCriteria",
    "AnthropicArticle",
    "AnthropicCategory",
    "AnthropicFilterCriteria",
]
