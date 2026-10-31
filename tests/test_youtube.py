"""Unit tests for YouTube scraper service and TranscriptService."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest
from youtube_transcript_api import (
    IpBlocked,
    NoTranscriptFound,
    TranscriptsDisabled,
    VideoUnavailable,
)

from app.scrapers.youtube import (
    YouTubeService,
    YouTubeVideo,
)
from app.services.transcript_service import TranscriptService, VideoTranscript


@pytest.fixture
def youtube_service():
    service = YouTubeService(channels=[])
    yield service
    service.close()


@pytest.fixture
def transcript_service():
    return TranscriptService()


# ---------------------------------------------------------------------------
# YouTube Feed & Channel Tests
# ---------------------------------------------------------------------------
def test_resolve_channel_id_direct(youtube_service):
    """Direct 24-character channel IDs should be recognized instantly."""
    cid = "UCbfYPyITQ-7l4upoX8nvctg"
    assert youtube_service.resolve_channel_id(cid) == cid


def test_resolve_channel_id_from_url(youtube_service):
    """Channel IDs in full URL paths should be extracted via regex."""
    url = "https://www.youtube.com/channel/UCbfYPyITQ-7l4upoX8nvctg"
    assert youtube_service.resolve_channel_id(url) == "UCbfYPyITQ-7l4upoX8nvctg"


def test_resolve_channel_id_from_handle(youtube_service):
    """Handles should be resolved via page inspection."""
    mock_html = """
    <html>
        <head>
            <link rel="canonical" href="https://www.youtube.com/channel/UCbfYPyITQ-7l4upoX8nvctg">
        </head>
    </html>
    """
    with patch.object(youtube_service.client, "get") as mock_get:
        mock_response = MagicMock()
        mock_response.text = mock_html
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        resolved = youtube_service.resolve_channel_id("@CustomCreator")
        assert resolved == "UCbfYPyITQ-7l4upoX8nvctg"
        # Second lookup should use cache
        assert youtube_service.resolve_channel_id("@CustomCreator") == "UCbfYPyITQ-7l4upoX8nvctg"
        assert mock_get.call_count == 1


def test_add_channel_dict(youtube_service):
    """Channels can be easily added as simple name + id dictionaries."""
    youtube_service.add_channel({"name": "Custom Channel", "id": "UC1234567890123456789012"})
    assert len(youtube_service.channels) == 1
    assert youtube_service.channels[0]["name"] == "Custom Channel"
    assert youtube_service.channels[0]["id"] == "UC1234567890123456789012"


def test_filter_by_time_24_hours(youtube_service):
    """Videos older than 24 hours should be excluded by filter_by_time."""
    now = datetime.now(timezone.utc)
    v_recent = YouTubeVideo(
        video_id="recent_1",
        title="Recent AI News",
        url="https://youtube.com/watch?v=recent_1",
        channel_id="UC1234567890123456789012",
        channel_name="AI News Channel",
        published_at=now - timedelta(hours=3),
    )
    v_borderline = YouTubeVideo(
        video_id="borderline_2",
        title="Just under 24h",
        url="https://youtube.com/watch?v=borderline_2",
        channel_id="UC1234567890123456789012",
        channel_name="AI News Channel",
        published_at=now - timedelta(hours=23, minutes=30),
    )
    v_old = YouTubeVideo(
        video_id="old_3",
        title="Old AI News",
        url="https://youtube.com/watch?v=old_3",
        channel_id="UC1234567890123456789012",
        channel_name="AI News Channel",
        published_at=now - timedelta(hours=25),
    )

    all_videos = [v_recent, v_borderline, v_old]
    filtered = youtube_service.filter_by_time(all_videos, hours_back=24)

    assert len(filtered) == 2
    assert [v.video_id for v in filtered] == ["recent_1", "borderline_2"]


# ---------------------------------------------------------------------------
# TranscriptService Tests
# ---------------------------------------------------------------------------
def test_extract_video_id(transcript_service):
    """TranscriptService should cleanly extract 11-char video IDs from various URL formats."""
    assert transcript_service.extract_video_id("CWdTBLsbaQs") == "CWdTBLsbaQs"
    assert transcript_service.extract_video_id("https://www.youtube.com/watch?v=CWdTBLsbaQs") == "CWdTBLsbaQs"
    assert transcript_service.extract_video_id("https://youtu.be/CWdTBLsbaQs") == "CWdTBLsbaQs"
    assert transcript_service.extract_video_id("https://www.youtube.com/shorts/7TtGMileCus") == "7TtGMileCus"


def test_transcript_service_success(transcript_service):
    """Test successful conversion of video speech into clean text."""
    mock_snippet_1 = MagicMock()
    mock_snippet_1.text = "Welcome to AI News today."
    mock_snippet_2 = MagicMock()
    mock_snippet_2.text = "Anthropic released Claude 3.5."

    mock_fetched = MagicMock()
    mock_fetched.snippets = [mock_snippet_1, mock_snippet_2]
    mock_fetched.language = "English"
    mock_fetched.language_code = "en"
    mock_fetched.is_generated = False

    with patch.object(transcript_service.api, "fetch", return_value=mock_fetched):
        result = transcript_service.get_transcript("CWdTBLsbaQs")
        assert result.available is True
        assert result.word_count == 9
        assert "Anthropic released Claude 3.5" in result.text
        assert result.error is None


def test_transcript_service_disabled(transcript_service):
    """When captions are disabled, it should report available=False without crashing."""
    with patch.object(
        transcript_service.api,
        "fetch",
        side_effect=TranscriptsDisabled("test_vid"),
    ):
        result = transcript_service.get_transcript("test_vid")
        assert result.available is False
        assert "disabled" in result.error.lower()


def test_transcript_service_ip_blocked(transcript_service):
    """When IP is rate limited by YouTube, report friendly error."""
    with patch.object(
        transcript_service.api,
        "fetch",
        side_effect=IpBlocked("test_vid"),
    ):
        result = transcript_service.get_transcript("test_vid")
        assert result.available is False
        assert "rate-limited" in result.error.lower() or "ipblocked" in result.error.lower()


def test_video_fetch_transcript_integration():
    """Calling video.fetch_transcript() delegates to TranscriptService."""
    now = datetime.now(timezone.utc)
    video = YouTubeVideo(
        video_id="vid_test_99",
        title="Test Integration Video",
        url="https://youtube.com/watch?v=vid_test_99",
        channel_id="UC1234567890123456789012",
        channel_name="AI Channel",
        published_at=now,
    )

    mock_transcript = VideoTranscript(
        video_id="vid_test_99",
        available=True,
        text="This is test knowledge text.",
        word_count=5,
    )

    with patch("app.scrapers.youtube.TranscriptService") as MockService:
        instance = MockService.return_value
        instance.get_transcript.return_value = mock_transcript

        t = video.fetch_transcript()
        assert t.available is True
        assert video.has_transcript is True
        assert video.transcript.text == "This is test knowledge text."
