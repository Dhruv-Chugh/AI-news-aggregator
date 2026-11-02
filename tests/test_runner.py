"""Unit tests for Unified Aggregation Runner Pipeline."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from app.config import SourcesConfig
from app.models.anthropic import AnthropicArticle
from app.models.openai import OpenAIArticle
from app.models.youtube import ChannelConfig, YouTubeVideo
from app.scrapers.runner import (
    AggregationResult,
    AggregationRunner,
    run_news_aggregation,
)


@pytest.fixture
def sample_aggregation_data():
    now = datetime.now(timezone.utc)
    vids = [
        YouTubeVideo(
            video_id="vid_1",
            title="Think School Analysis",
            url="https://youtube.com/watch?v=vid_1",
            channel_id="UCKZozRVHRYsYHGEyNKuhhdA",
            channel_name="Think School",
            published_at=now - timedelta(hours=2),
        )
    ]
    oai = [
        OpenAIArticle(
            article_id="oai_1",
            title="OpenAI Alignment Research",
            url="https://openai.com/index/oai-alignment",
            published_at=now - timedelta(hours=5),
            summary="New alignment benchmark",
        )
    ]
    ant = [
        AnthropicArticle(
            article_id="ant_1",
            title="Anthropic Drug Discovery",
            url="https://anthropic.com/research/drug-discovery",
            published_at=now - timedelta(hours=8),
            summary="Accelerating drug discovery",
        )
    ]
    return vids, oai, ant


def test_aggregation_result_properties(sample_aggregation_data):
    """Test counts, summary, and properties on AggregationResult."""
    vids, oai, ant = sample_aggregation_data
    result = AggregationResult(
        hours_back=24,
        youtube_videos=vids,
        openai_articles=oai,
        anthropic_articles=ant,
    )

    assert result.total_items == 3
    assert result.has_items is True
    assert result.summary_counts == {
        "youtube": 1,
        "openai": 1,
        "anthropic": 1,
        "total": 3,
    }


def test_aggregation_runner_full_orchestration(sample_aggregation_data, tmp_path):
    """Test AggregationRunner orchestrating all 3 scrapers."""
    vids, oai, ant = sample_aggregation_data

    with patch("app.scrapers.runner.YouTubeService") as mock_yt_cls, \
         patch("app.scrapers.runner.OpenAIScraperService") as mock_oai_cls, \
         patch("app.scrapers.runner.AnthropicScraperService") as mock_ant_cls:

        mock_yt_inst = MagicMock()
        mock_yt_inst.get_recent_videos.return_value = vids
        mock_yt_cls.return_value.__enter__.return_value = mock_yt_inst

        mock_oai_inst = MagicMock()
        mock_oai_inst.get_recent_articles.return_value = oai
        mock_oai_cls.return_value.__enter__.return_value = mock_oai_inst

        mock_ant_inst = MagicMock()
        mock_ant_inst.get_articles.return_value = ant
        mock_ant_cls.return_value.__enter__.return_value = mock_ant_inst

        dest_md = tmp_path / "test_digest.md"

        with AggregationRunner() as runner:
            result = runner.run(
                hours_back=24,
                export_markdown=True,
                export_path=str(dest_md),
            )

        assert result.total_items == 3
        assert len(result.youtube_videos) == 1
        assert len(result.openai_articles) == 1
        assert len(result.anthropic_articles) == 1
        assert result.export_path == str(dest_md.resolve())
        assert dest_md.exists()


def test_aggregation_runner_toggling_sources(sample_aggregation_data):
    """Verify that disabling specific sources skips their execution."""
    vids, oai, ant = sample_aggregation_data

    with patch("app.scrapers.runner.YouTubeService") as mock_yt_cls, \
         patch("app.scrapers.runner.OpenAIScraperService") as mock_oai_cls, \
         patch("app.scrapers.runner.AnthropicScraperService") as mock_ant_cls:

        mock_oai_inst = MagicMock()
        mock_oai_inst.get_recent_articles.return_value = oai
        mock_oai_cls.return_value.__enter__.return_value = mock_oai_inst

        with AggregationRunner() as runner:
            # Disable YouTube and Anthropic
            result = runner.run(
                hours_back=24,
                include_youtube=False,
                include_openai=True,
                include_anthropic=False,
                export_markdown=False,
            )

        mock_yt_cls.assert_not_called()
        mock_ant_cls.assert_not_called()
        assert len(result.youtube_videos) == 0
        assert len(result.openai_articles) == 1
        assert len(result.anthropic_articles) == 0


def test_aggregation_runner_error_resilience(sample_aggregation_data):
    """Ensure that if one source fails, others succeed and error is captured as warning."""
    vids, oai, ant = sample_aggregation_data

    with patch("app.scrapers.runner.YouTubeService") as mock_yt_cls, \
         patch("app.scrapers.runner.OpenAIScraperService") as mock_oai_cls, \
         patch("app.scrapers.runner.AnthropicScraperService") as mock_ant_cls:

        mock_yt_cls.side_effect = Exception("YouTube connection timed out")

        mock_oai_inst = MagicMock()
        mock_oai_inst.get_recent_articles.return_value = oai
        mock_oai_cls.return_value.__enter__.return_value = mock_oai_inst

        mock_ant_inst = MagicMock()
        mock_ant_inst.get_articles.return_value = ant
        mock_ant_cls.return_value.__enter__.return_value = mock_ant_inst

        with AggregationRunner() as runner:
            result = runner.run(hours_back=24, export_markdown=False)

        assert len(result.youtube_videos) == 0
        assert len(result.openai_articles) == 1
        assert len(result.anthropic_articles) == 1
        assert len(result.warnings) == 1
        assert "YouTube aggregation failed" in result.warnings[0]


def test_run_news_aggregation_streamlined_function(sample_aggregation_data):
    """Verify run_news_aggregation helper function."""
    vids, oai, ant = sample_aggregation_data

    with patch("app.scrapers.runner.AggregationRunner.run") as mock_run:
        mock_run.return_value = AggregationResult(
            hours_back=24,
            youtube_videos=vids,
            openai_articles=oai,
            anthropic_articles=ant,
        )

        res = run_news_aggregation(hours_back=24, export_markdown=False)
        assert res.total_items == 3
        mock_run.assert_called_once()
