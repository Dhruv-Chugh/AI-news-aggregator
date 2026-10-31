"""Transcript Service (OOP Architecture with Pydantic).

Extracts spoken transcript knowledge from YouTube videos using youtube-transcript-api.
Provides clean OOP classes, Pydantic data schemas, and proxy resilience.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from typing import Any, List, Optional, Tuple

from youtube_transcript_api import (
    CouldNotRetrieveTranscript,
    IpBlocked,
    NoTranscriptFound,
    RequestBlocked,
    TranscriptsDisabled,
    VideoUnavailable,
    YouTubeTranscriptApi,
    YouTubeTranscriptApiException,
)
from youtube_transcript_api.proxies import GenericProxyConfig

from app.models.youtube import (
    TranscriptSnippet,
    VideoTranscript,
    YouTubeVideo,
)

logger = logging.getLogger("ai_news.transcript")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class TranscriptIdParser:
    """Helper class to parse and validate YouTube video identifiers."""

    @staticmethod
    def extract_video_id(video_input: str) -> str:
        """Extract a clean video ID from raw ID, watch URL, short URL, or embed link.

        Examples:
            - 'CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://www.youtube.com/watch?v=CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://youtu.be/CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://www.youtube.com/shorts/7TtGMileCus' -> '7TtGMileCus'
        """
        cleaned = video_input.strip()

        # If it's already a clean ID string without URL delimiters
        if not any(c in cleaned for c in "/?=&:") and 6 <= len(cleaned) <= 30:
            return cleaned

        # Watch URL: ?v=VIDEO_ID
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        # Short URL or Shorts: youtu.be/ID or /shorts/ID
        match = re.search(r"(?:youtu\.be/|/shorts/|/embed/)([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        # Fallback regex search for any 11-char pattern
        match = re.search(r"([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract a valid YouTube video ID from: '{video_input}'")


class TranscriptCleaner:
    """Helper class to clean and format transcript text."""

    @staticmethod
    def clean(snippets: List[Any]) -> Tuple[str, List[TranscriptSnippet]]:
        """Clean raw snippet objects into normalized text and Pydantic TranscriptSnippet models."""
        pydantic_snippets: List[TranscriptSnippet] = []
        raw_pieces: List[str] = []

        for s in snippets:
            text = getattr(s, "text", "") or ""
            text = text.strip()
            if not text:
                continue

            raw_pieces.append(text)
            start = float(getattr(s, "start", 0.0))
            duration = float(getattr(s, "duration", 0.0))
            pydantic_snippets.append(
                TranscriptSnippet(start=start, duration=duration, text=text)
            )

        combined = " ".join(raw_pieces)
        normalized = re.sub(r"\s+", " ", combined).strip()
        return normalized, pydantic_snippets


class TranscriptService:
    """Object-Oriented Service to convert YouTube video speech into text knowledge."""

    def __init__(self, proxy_url: Optional[str] = None) -> None:
        """Initialize TranscriptService with optional proxy configuration.

        Args:
            proxy_url: Optional HTTP/HTTPS proxy string. Defaults to YOUTUBE_PROXY or HTTPS_PROXY env var.
        """
        active_proxy = proxy_url or os.getenv("YOUTUBE_PROXY") or os.getenv("HTTPS_PROXY")
        proxy_config = None
        if active_proxy:
            proxy_config = GenericProxyConfig(http_url=active_proxy, https_url=active_proxy)
            logger.info("TranscriptService initialized with proxy: %s", active_proxy)

        self.api = YouTubeTranscriptApi(proxy_config=proxy_config)
        self.id_parser = TranscriptIdParser()
        self.cleaner = TranscriptCleaner()

    def get_transcript(
        self,
        video_input: str,
        languages: Tuple[str, ...] = ("en", "en-US", "en-GB"),
    ) -> VideoTranscript:
        """Fetch transcript for a given video ID or URL, returning a Pydantic VideoTranscript model."""
        video_id = self.id_parser.extract_video_id(video_input)

        try:
            # 1. Primary attempt: fetch with specified languages
            fetched = self.api.fetch(video_id, languages=languages)
            clean_text, snippets = self.cleaner.clean(fetched.snippets)

            return VideoTranscript(
                video_id=video_id,
                available=True,
                text=clean_text,
                language=fetched.language,
                language_code=fetched.language_code,
                is_generated=fetched.is_generated,
                word_count=len(clean_text.split()),
                character_count=len(clean_text),
                snippets=snippets,
            )

        except (IpBlocked, RequestBlocked):
            logger.warning("YouTube timedtext rate-limited IP (IpBlocked) for video: %s", video_id)
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason="YouTube temporarily rate-limited IP for caption requests (IpBlocked).",
            )

        except TranscriptsDisabled:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason="Transcripts are disabled by the creator for this video.",
            )

        except VideoUnavailable:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason="Video is private, restricted, or unavailable.",
            )

        except (NoTranscriptFound, CouldNotRetrieveTranscript):
            # 2. Fallback: try finding any generated transcript or alternate language
            try:
                transcript_list = self.api.list(video_id)
                found = None

                # Look for preferred languages first
                try:
                    found = transcript_list.find_transcript(list(languages))
                except Exception:
                    # Otherwise take first available transcript
                    for t in transcript_list:
                        found = t
                        break

                if found:
                    fetched = found.fetch()
                    clean_text, snippets = self.cleaner.clean(fetched.snippets)
                    return VideoTranscript(
                        video_id=video_id,
                        available=True,
                        text=clean_text,
                        language=fetched.language,
                        language_code=fetched.language_code,
                        is_generated=fetched.is_generated,
                        word_count=len(clean_text.split()),
                        character_count=len(clean_text),
                        snippets=snippets,
                    )
            except Exception as e:
                logger.debug("Fallback transcript search failed for %s: %s", video_id, e)

            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason="No transcript found for this video.",
            )

        except YouTubeTranscriptApiException as e:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason=f"YouTube transcript error: {str(e)}",
            )

        except Exception as e:
            logger.warning("Unexpected error extracting transcript for %s: %s", video_id, e)
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error_reason=f"Unexpected error: {str(e)}",
            )

    def get_text_only(
        self,
        video_input: str,
        languages: Tuple[str, ...] = ("en", "en-US", "en-GB"),
    ) -> str:
        """Convenience method returning raw string content or empty string."""
        result = self.get_transcript(video_input, languages=languages)
        return result.text if result.available else ""

    def enrich_video(self, video: YouTubeVideo) -> YouTubeVideo:
        """OOP method to attach a fetched transcript to an existing YouTubeVideo model."""
        video.transcript = self.get_transcript(video.video_id)
        return video


def main() -> None:
    """CLI to inspect and convert any YouTube video to text."""
    parser = argparse.ArgumentParser(
        description="Convert YouTube Video Knowledge into Text using Transcripts (OOP & Pydantic)"
    )
    parser.add_argument(
        "video",
        type=str,
        help="YouTube Video ID or Full URL (e.g. 'DHzC4VVmolk' or 'https://www.youtube.com/watch?v=...')",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=500,
        help="Number of characters to preview in terminal (default: 500)",
    )

    args = parser.parse_args()

    service = TranscriptService()
    print("=" * 70)
    print("YOUTUBE TRANSCRIPT SERVICE (OOP & PYDANTIC)")
    print("=" * 70)

    result = service.get_transcript(args.video)

    if result.available:
        print(f"[SUCCESS] Transcript Extracted:")
        print(f"  • Video ID:        {result.video_id}")
        print(f"  • Words:           {result.word_count:,}")
        print(f"  • Characters:      {result.character_count:,}")
        print(f"  • Language:        {result.language} ({result.language_code})")
        print(f"  • Auto-Generated:  {result.is_generated}")
        print(f"  • Total Snippets:  {len(result.snippets)}")
        print("-" * 70)

        if args.preview > 0:
            print(f"Preview (first {args.preview} chars):\n")
            print(result.text[: args.preview] + "...")
        else:
            print("Full Transcript:\n")
            print(result.text)
    else:
        print(f"[UNAVAILABLE] Video ID: {result.video_id}")
        print(f"Reason: {result.error_reason}")

    print("=" * 70)


if __name__ == "__main__":
    main()
