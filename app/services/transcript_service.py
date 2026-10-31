"""Transcript Service.

Converts YouTube video audio/knowledge into clean text using youtube-transcript-api.
Can be used independently or combined with YouTube RSS video discovery.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field
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

logger = logging.getLogger("ai_news.transcript")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


class VideoTranscript(BaseModel):
    """Clean representation of extracted video transcript knowledge."""

    video_id: str
    available: bool = Field(default=False, description="Whether transcript retrieval succeeded")
    text: str = Field(default="", description="Full aggregated transcript text")
    word_count: int = Field(default=0, description="Total words in transcript")
    language: Optional[str] = Field(default=None, description="Language name")
    language_code: Optional[str] = Field(default=None, description="Language ISO code")
    is_generated: bool = Field(default=False, description="Whether transcript is auto-generated")
    error: Optional[str] = Field(default=None, description="Reason if transcript was not available")


class TranscriptService:
    """Service to fetch and convert YouTube video speech into text."""

    def __init__(self, proxy_url: Optional[str] = None) -> None:
        """Initialize TranscriptService with optional proxy support to prevent IP bans.

        Can be provided directly or via YOUTUBE_PROXY / HTTPS_PROXY env vars.
        """
        active_proxy = proxy_url or os.getenv("YOUTUBE_PROXY") or os.getenv("HTTPS_PROXY")
        proxy_config = None
        if active_proxy:
            proxy_config = GenericProxyConfig(http_url=active_proxy, https_url=active_proxy)
            logger.info("Using configured proxy for YouTube transcript requests: %s", active_proxy)

        self.api = YouTubeTranscriptApi(proxy_config=proxy_config)

    @staticmethod
    def extract_video_id(video_input: str) -> str:
        """Extract a video ID from a raw ID or full YouTube URL.

        Examples:
            - 'CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://www.youtube.com/watch?v=CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://youtu.be/CWdTBLsbaQs' -> 'CWdTBLsbaQs'
            - 'https://www.youtube.com/shorts/7TtGMileCus' -> '7TtGMileCus'
        """
        cleaned = video_input.strip()

        # If it's already a raw ID without URL symbols
        if not any(c in cleaned for c in "/?=&:") and 6 <= len(cleaned) <= 30:
            return cleaned

        # Standard watch URL: ?v=VIDEO_ID
        match = re.search(r"[?&]v=([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        # Short URL: youtu.be/VIDEO_ID or youtube.com/shorts/VIDEO_ID
        match = re.search(r"(?:youtu\.be/|/shorts/|/embed/)([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        # Fallback regex search for any 11-char pattern
        match = re.search(r"([a-zA-Z0-9_-]{11})", cleaned)
        if match:
            return match.group(1)

        raise ValueError(f"Could not extract a valid YouTube video ID from: '{video_input}'")

    def get_transcript(
        self,
        video_input: str,
        languages: Tuple[str, ...] = ("en", "en-US", "en-GB"),
    ) -> VideoTranscript:
        """Fetch transcript for a given video ID or URL.

        Args:
            video_input: 11-char video ID or any YouTube video URL.
            languages: Tuple of language codes in order of preference.

        Returns:
            VideoTranscript object containing text, word count, and metadata.
        """
        video_id = self.extract_video_id(video_input)

        try:
            # 1. Try direct fetch with requested languages
            fetched = self.api.fetch(video_id, languages=languages)
            text = self._clean_transcript_text(fetched.snippets)

            return VideoTranscript(
                video_id=video_id,
                available=True,
                text=text,
                word_count=len(text.split()),
                language=fetched.language,
                language_code=fetched.language_code,
                is_generated=fetched.is_generated,
            )

        except (IpBlocked, RequestBlocked):
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error="YouTube temporarily rate-limited IP for caption requests (IpBlocked).",
            )

        except TranscriptsDisabled:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error="Transcripts are disabled by the creator for this video.",
            )

        except VideoUnavailable:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error="Video is private, restricted, or unavailable.",
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
                    # Otherwise pick first available transcript
                    for t in transcript_list:
                        found = t
                        break

                if found:
                    fetched = found.fetch()
                    text = self._clean_transcript_text(fetched.snippets)
                    return VideoTranscript(
                        video_id=video_id,
                        available=True,
                        text=text,
                        word_count=len(text.split()),
                        language=fetched.language,
                        language_code=fetched.language_code,
                        is_generated=fetched.is_generated,
                    )
            except Exception as e:
                logger.debug("Fallback transcript search failed for %s: %s", video_id, e)

            return VideoTranscript(
                video_id=video_id,
                available=False,
                error="No transcript found for this video.",
            )

        except YouTubeTranscriptApiException as e:
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error=f"YouTube transcript error: {str(e)}",
            )

        except Exception as e:
            logger.warning("Unexpected error extracting transcript for %s: %s", video_id, e)
            return VideoTranscript(
                video_id=video_id,
                available=False,
                error=f"Unexpected error: {str(e)}",
            )

    def get_text_only(
        self,
        video_input: str,
        languages: Tuple[str, ...] = ("en", "en-US", "en-GB"),
    ) -> str:
        """Convenience method that returns just the plain text string of the transcript.

        Returns empty string if unavailable.
        """
        result = self.get_transcript(video_input, languages=languages)
        return result.text if result.available else ""

    @staticmethod
    def _clean_transcript_text(snippets: List[Any]) -> str:
        """Join snippet pieces and normalize whitespace into clean sentences."""
        raw_pieces = [s.text.strip() for s in snippets if s.text and s.text.strip()]
        # Join into single readable text
        combined = " ".join(raw_pieces)
        # Normalize double spaces or newline artifacts
        clean = re.sub(r"\s+", " ", combined).strip()
        return clean


def main() -> None:
    """CLI to convert any YouTube video to text."""
    parser = argparse.ArgumentParser(
        description="Convert YouTube Video Knowledge into Text using Transcripts"
    )
    parser.add_argument(
        "video",
        type=str,
        help="YouTube Video ID or Full URL (e.g. 'CWdTBLsbaQs' or 'https://www.youtube.com/watch?v=CWdTBLsbaQs')",
    )
    parser.add_argument(
        "--preview",
        type=int,
        default=500,
        help="Number of characters to preview in terminal (0 for full text, default 500)",
    )

    args = parser.parse_args()

    service = TranscriptService()
    print("=" * 70)
    print("YOUTUBE TRANSCRIPT SERVICE")
    print("=" * 70)

    try:
        vid = service.extract_video_id(args.video)
        print(f"Target Video ID: {vid}")
        print("Extracting transcript knowledge...")
        result = service.get_transcript(vid)

        if result.available:
            print("\n[SUCCESS] Transcript Extracted:")
            print(f"  • Words:        {result.word_count:,}")
            print(f"  • Language:     {result.language} ({result.language_code})")
            print(f"  • Auto-Generated: {result.is_generated}")
            print("-" * 70)

            if args.preview > 0:
                print(f"Preview (first {args.preview} chars):\n")
                print(result.text[: args.preview] + "...")
            else:
                print("Full Transcript:\n")
                print(result.text)
        else:
            print(f"\n[UNAVAILABLE] {result.error}")

    except Exception as e:
        print(f"\n[ERROR] {e}")

    print("=" * 70)


if __name__ == "__main__":
    main()
