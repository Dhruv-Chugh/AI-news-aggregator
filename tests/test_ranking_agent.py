"""Unit tests for Personalized User Interest Ranking Agent and 24-Hour Scheduler."""

from datetime import date, datetime, timedelta, timezone
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.agent.ranking_agent import (
    UserRankingAgent,
    apply_source_diversity_limit,
    classify_source_diversity_tiers,
    extract_quick_summary,
)
from app.agent.ranking_schemas import (
    CandidateDigestInput,
    PersonalizedRankingOutput,
    RankedDigestItem,
    UserProfileData,
)
from app.agent.ranking_scheduler import RankingSchedulerService
from app.database.models import Article, ArticleDigest, Base, Source, Subscriber, UserDigestRanking
from app.database.repository import NewsRepository


@pytest.fixture
def test_engine():
    """Create an isolated, in-memory SQLite engine for tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(test_engine) -> Generator[Session, None, None]:
    """Yield a database session bound to the in-memory test engine."""
    session_factory = sessionmaker(bind=test_engine, expire_on_commit=False)
    session = session_factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def populated_db(db_session: Session) -> dict:
    """Populate database with sources, articles, summaries in table 'digest', and 2 subscribers."""
    repo = NewsRepository(session=db_session)

    # 1. Sources
    yt = repo.sources.create("Figuring Out", "youtube", "https://youtube.com/@rajshamani")
    oa = repo.sources.create("OpenAI", "openai", "https://openai.com/news")
    an = repo.sources.create("Anthropic", "anthropic", "https://anthropic.com/news")

    now = datetime.now(timezone.utc)

    # 2. Articles
    art_super = repo.articles.create(
        source_id=yt.id,
        external_id="art-super",
        title="Sam Altman On Superintelligence and Compute Scaling",
        url="https://youtube.com/watch?v=123",
        published_at=now,
        word_count=12000,
    )
    art_scidisc = repo.articles.create(
        source_id=an.id,
        external_id="art-scidisc",
        title="AI for Scientific Discovery: How Researchers Use Claude",
        url="https://anthropic.com/research/claude-science",
        published_at=now,
        word_count=7500,
    )
    art_acq = repo.articles.create(
        source_id=oa.id,
        external_id="art-acq",
        title="OpenAI Acquires Pierre Computer Company",
        url="https://openai.com/index/acquire-pierre",
        published_at=now,
        word_count=450,
    )

    # 3. Digest summaries in table 'digest'
    d1 = repo.article_digests.create(
        article_id=art_super.id,
        title=art_super.title,
        url=art_super.url,
        source_name="Figuring Out",
        source_type="youtube",
        summary="A half-page discussion on datacenter compute, energy scaling, and agent architectures...",
        problem_statement="Global energy constraints for frontier datacenter clusters.",
        solution_statement="Nuclear modular power and custom accelerator silicon.",
        key_insights=["Compute scaling curves continue unabated.", "Agents will reshape work by 2026."],
        model_used="gemini:interactions/gemini-2.5-flash",
    )
    d2 = repo.article_digests.create(
        article_id=art_scidisc.id,
        title=art_scidisc.title,
        url=art_scidisc.url,
        source_name="Anthropic",
        source_type="anthropic",
        summary="Comprehensive analysis of how Claude accelerates protein folding, mathematics, and chemistry...",
        problem_statement="Scientific discovery bottlenecked by human researcher bandwidth.",
        solution_statement="Claude Science specialized tool use and automated hypothesis verification.",
        key_insights=["Accelerates drug discovery cycle times.", "Enables autonomous symbolic mathematics."],
        model_used="gemini:interactions/gemini-2.5-flash",
    )
    d3 = repo.article_digests.create(
        article_id=art_acq.id,
        title=art_acq.title,
        url=art_acq.url,
        source_name="OpenAI",
        source_type="openai",
        summary="Corporate acquisition of Pierre to integrate collaborative desktop workflows...",
        problem_statement="Fragmented desktop computing workflows for team collaboration.",
        solution_statement="Direct acquisition of Pierre design and engineering team.",
        key_insights=["Strengthens design talent at OpenAI."],
        model_used="openai:responses/gpt-4o-mini",
    )

    # 4. Subscribers with distinct user interest profiles
    sub_scientist = repo.subscribers.create(
        email="scientist@biotech.org",
        name="Dr. Sarah Chen",
        bio_or_role="Computational Biologist & AI Researcher",
        expertise_level="expert",
        interests=["scientific discovery", "biology", "chemistry", "reasoning", "claude"],
        preferred_sources=["anthropic"],
        ranking_instructions="Prioritize empirical scientific breakthroughs and research acceleration.",
    )
    sub_founder = repo.subscribers.create(
        email="founder@venturetech.com",
        name="Alex Rivera",
        bio_or_role="AI Startup Founder & Tech Strategist",
        expertise_level="advanced",
        interests=["superintelligence", "compute scaling", "venture capital", "energy", "agents"],
        preferred_sources=["youtube", "openai"],
        ranking_instructions="Prioritize macro strategy, compute bottlenecks, and platform disruption.",
    )

    db_session.commit()
    return {
        "sources": [yt, oa, an],
        "articles": [art_super, art_scidisc, art_acq],
        "digests": [d1, d2, d3],
        "subscribers": [sub_scientist, sub_founder],
    }


# =========================================================================
# 1. Schema & Model Tests
# =========================================================================


def test_user_profile_schemas():
    """Verify UserProfileData and RankedDigestItem schemas."""
    user = UserProfileData(
        subscriber_id=1,
        email="user@ai.com",
        name="Test User",
        bio_or_role="AI Engineer",
        expertise_level="advanced",
        interests=["agents", "reinforcement learning"],
        preferred_sources=["openai", "anthropic"],
    )
    assert user.subscriber_id == 1
    assert "agents" in user.interests

    ranked_item = RankedDigestItem(
        digest_id=10,
        title="Scaling Frontier Models",
        url="https://openai.com/123",
        rank_position=1,
        rank_score=94.5,
        relevance_reasoning="Direct match for reinforcement learning interests.",
        personalized_takeaways=["Explore agent design patterns."],
    )
    assert ranked_item.rank_score == 94.5
    assert ranked_item.rank_position == 1


# =========================================================================
# 2. Repository Tests for Table 'user_digest_rankings'
# =========================================================================


def test_user_digest_ranking_repository_crud(db_session: Session, populated_db):
    """Test CRUD operations on user_digest_rankings table."""
    repo = NewsRepository(session=db_session)
    sub = populated_db["subscribers"][0]
    dig = populated_db["digests"][0]
    today = date.today()

    # 1. Create ranking entry
    entry = repo.user_rankings.create(
        subscriber_id=sub.id,
        digest_id=dig.id,
        rank_position=1,
        rank_score=95.0,
        relevance_reasoning="Top priority alignment with research goals.",
        key_takeaways_for_user=["Review compute requirements."],
        batch_date=today,
    )
    db_session.commit()

    assert entry.id is not None
    assert entry.rank_score == 95.0

    # 2. Fetch rankings for subscriber
    results = repo.user_rankings.get_rankings_for_subscriber(sub.id, batch_date=today)
    assert len(results) == 1
    assert results[0].digest_id == dig.id
    assert results[0].digest.title == dig.title

    # 3. Clear batch
    cleared = repo.user_rankings.clear_subscriber_batch(sub.id, today)
    db_session.commit()
    assert cleared == 1
    assert len(repo.user_rankings.get_rankings_for_subscriber(sub.id, batch_date=today)) == 0


def test_cascade_delete_subscriber_removes_rankings(db_session: Session, populated_db):
    """Verify that deleting a subscriber cascade deletes their rankings."""
    repo = NewsRepository(session=db_session)
    sub = populated_db["subscribers"][0]
    dig = populated_db["digests"][0]

    repo.user_rankings.create(
        subscriber_id=sub.id,
        digest_id=dig.id,
        rank_position=1,
        rank_score=90.0,
        relevance_reasoning="Test cascade.",
    )
    db_session.commit()

    # Delete subscriber
    repo.subscribers.delete(sub.email)
    db_session.commit()

    # Verify ranking record is deleted
    rankings = db_session.query(UserDigestRanking).filter_by(subscriber_id=sub.id).all()
    assert len(rankings) == 0


# =========================================================================
# 3. Personalized Ranking Agent Behavior Tests
# =========================================================================


def test_ranking_agent_distinct_user_interests(db_session: Session, populated_db):
    """Verify that two users with different interests receive distinct, personalized rankings."""
    agent = UserRankingAgent(session=db_session, preferred_provider="auto")

    # Run daily ranking for all subscribers
    report = agent.run_daily_ranking(hours=24)

    assert report.subscribers_evaluated == 2
    assert report.rankings_stored == 6  # 3 digests x 2 subscribers

    scientist_briefing = report.rankings_by_subscriber["scientist@biotech.org"]
    founder_briefing = report.rankings_by_subscriber["founder@venturetech.com"]

    # The computational biologist should have Anthropic "Claude for Scientific Discovery" as #1
    scientist_top_item = scientist_briefing["items"][0]
    assert "scientific discovery" in scientist_top_item["title"].lower() or "claude" in scientist_top_item["title"].lower()
    assert scientist_top_item["rank_score"] > 80.0

    # The AI founder should have Sam Altman on Superintelligence / Compute Scaling as #1
    founder_top_item = founder_briefing["items"][0]
    assert "superintelligence" in founder_top_item["title"].lower() or "sam altman" in founder_top_item["title"].lower()
    assert founder_top_item["rank_score"] > 80.0

    # Verify that rank positions are ordered 1, 2, 3
    for sub_data in [scientist_briefing, founder_briefing]:
        positions = [item["rank_position"] for item in sub_data["items"]]
        assert positions == [1, 2, 3]
        scores = [item["rank_score"] for item in sub_data["items"]]
        assert scores == sorted(scores, reverse=True)


def test_ranking_agent_export_markdown(db_session: Session, populated_db):
    """Test generating a personalized markdown report for a subscriber."""
    agent = UserRankingAgent(session=db_session, preferred_provider="auto")
    agent.run_daily_ranking()

    md = agent.export_personalized_markdown("scientist@biotech.org")
    assert "# 🎯 Daily Personalized AI Intelligence Briefing" in md
    assert "Dr. Sarah Chen" in md
    assert "Computational Biologist" in md
    assert "# 🌟 Featured Deep Dives" in md
    assert "Why This Matters For You" in md
    assert "Personalized Takeaways For Your Role" in md


# =========================================================================
# 4. 24-Hour Scheduler Tests
# =========================================================================


def test_ranking_scheduler_registration(db_session: Session):
    """Verify RankingSchedulerService registers the 24-hour interval job."""
    service = RankingSchedulerService(interval_hours=24, blocking=False)
    service.setup_job(run_on_start=False)

    jobs = service.scheduler.get_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.id == "user_interest_ranking_24h"
    assert job.name == "24-Hour Personalized User Ranking"


# =========================================================================
# 5. Source Diversity Balancing Tests (Max 2 Per Source)
# =========================================================================


def test_apply_source_diversity_limit_caps_at_two():
    """Verify that when sources have >2 items, only top 2 are selected, while <=2 are preserved."""
    items = [
        RankedDigestItem(
            digest_id=1,
            title="OpenAI Item 1",
            url="https://openai.com/1",
            rank_position=1,
            rank_score=95.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T1"],
            source_name="OpenAI",
            source_type="openai",
        ),
        RankedDigestItem(
            digest_id=2,
            title="YouTube Item 1",
            url="https://youtube.com/1",
            rank_position=2,
            rank_score=92.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T2"],
            source_name="YouTube",
            source_type="youtube",
        ),
        RankedDigestItem(
            digest_id=3,
            title="OpenAI Item 2",
            url="https://openai.com/2",
            rank_position=3,
            rank_score=90.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T3"],
            source_name="OpenAI",
            source_type="openai",
        ),
        RankedDigestItem(
            digest_id=4,
            title="YouTube Item 2",
            url="https://youtube.com/2",
            rank_position=4,
            rank_score=88.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T4"],
            source_name="YouTube",
            source_type="youtube",
        ),
        RankedDigestItem(
            digest_id=5,
            title="OpenAI Item 3 (Should be pruned)",
            url="https://openai.com/3",
            rank_position=5,
            rank_score=85.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T5"],
            source_name="OpenAI",
            source_type="openai",
        ),
        RankedDigestItem(
            digest_id=6,
            title="Anthropic Item 1 (Kept because <=2)",
            url="https://anthropic.com/1",
            rank_position=6,
            rank_score=82.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T6"],
            source_name="Anthropic",
            source_type="anthropic",
        ),
        RankedDigestItem(
            digest_id=7,
            title="OpenAI Item 4 (Should be pruned)",
            url="https://openai.com/4",
            rank_position=7,
            rank_score=80.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T7"],
            source_name="OpenAI",
            source_type="openai",
        ),
        RankedDigestItem(
            digest_id=8,
            title="YouTube Item 3 (Should be pruned)",
            url="https://youtube.com/3",
            rank_position=8,
            rank_score=70.0,
            relevance_reasoning="Great",
            personalized_takeaways=["T8"],
            source_name="YouTube",
            source_type="youtube",
        ),
    ]

    balanced = apply_source_diversity_limit(items, max_per_source=2)

    # Total items should be 2 (OpenAI) + 2 (YouTube) + 1 (Anthropic) = 5
    assert len(balanced) == 5

    # Check counts per source
    openai_count = sum(1 for it in balanced if it.source_type == "openai")
    yt_count = sum(1 for it in balanced if it.source_type == "youtube")
    ant_count = sum(1 for it in balanced if it.source_type == "anthropic")

    assert openai_count == 2
    assert yt_count == 2
    assert ant_count == 1

    # Check contiguous rank positions 1, 2, 3, 4, 5
    assert [it.rank_position for it in balanced] == [1, 2, 3, 4, 5]

    # Check strictly descending score order preserved
    scores = [it.rank_score for it in balanced]
    assert scores == [95.0, 92.0, 90.0, 88.0, 82.0]

    # Verify pruned items are NOT present
    digest_ids = [it.digest_id for it in balanced]
    assert 5 not in digest_ids
    assert 7 not in digest_ids
    assert 8 not in digest_ids


def test_ranking_agent_deterministic_matcher_diversity_limit(db_session: Session):
    """Verify that rank_for_user with max_per_source=2 enforces balanced source inclusion."""
    agent = UserRankingAgent(session=db_session, preferred_provider="auto")

    user = UserProfileData(
        subscriber_id=1,
        email="test@example.com",
        name="Test Engineer",
        bio_or_role="ML Researcher",
        expertise_level="advanced",
        interests=["llm", "agents", "reasoning"],
    )

    # 4 OpenAI, 3 YouTube, 1 Anthropic candidates
    candidates = [
        CandidateDigestInput(
            digest_id=1,
            article_id=101,
            title="OpenAI Agents SDK 1",
            url="https://openai.com/1",
            source_name="OpenAI",
            source_type="openai",
            summary="Agents SDK details...",
        ),
        CandidateDigestInput(
            digest_id=2,
            article_id=102,
            title="OpenAI Agents SDK 2",
            url="https://openai.com/2",
            source_name="OpenAI",
            source_type="openai",
            summary="Agents SDK details 2...",
        ),
        CandidateDigestInput(
            digest_id=3,
            article_id=103,
            title="OpenAI Agents SDK 3",
            url="https://openai.com/3",
            source_name="OpenAI",
            source_type="openai",
            summary="Agents SDK details 3...",
        ),
        CandidateDigestInput(
            digest_id=4,
            article_id=104,
            title="YouTube Agent Tutorial 1",
            url="https://youtube.com/1",
            source_name="YouTube",
            source_type="youtube",
            summary="YouTube video on agents...",
        ),
        CandidateDigestInput(
            digest_id=5,
            article_id=105,
            title="YouTube Agent Tutorial 2",
            url="https://youtube.com/2",
            source_name="YouTube",
            source_type="youtube",
            summary="YouTube video 2 on agents...",
        ),
        CandidateDigestInput(
            digest_id=6,
            article_id=106,
            title="YouTube Agent Tutorial 3",
            url="https://youtube.com/3",
            source_name="YouTube",
            source_type="youtube",
            summary="YouTube video 3 on agents...",
        ),
        CandidateDigestInput(
            digest_id=7,
            article_id=107,
            title="Anthropic Claude Research",
            url="https://anthropic.com/claude",
            source_name="Anthropic",
            source_type="anthropic",
            summary="Claude 3.7 Sonnet reasoning...",
        ),
    ]

    result = agent.rank_for_user(user, candidates, max_per_source=2)

    # All 7 items are kept (0 dropped)
    assert len(result.ranked_items) == 7

    # 5 items should be featured: 2 OpenAI, 2 YouTube, 1 Anthropic
    featured_items = [it for it in result.ranked_items if it.tier == "featured"]
    assert len(featured_items) == 5

    featured_counts = {}
    for item in featured_items:
        st = item.source_type or "unknown"
        featured_counts[st] = featured_counts.get(st, 0) + 1

    assert featured_counts.get("openai", 0) == 2
    assert featured_counts.get("youtube", 0) == 2
    assert featured_counts.get("anthropic", 0) == 1

    # 2 items should be quick_bites: 1 OpenAI, 1 YouTube
    quick_bites = [it for it in result.ranked_items if it.tier == "quick_bite"]
    assert len(quick_bites) == 2
    for qb in quick_bites:
        assert qb.quick_summary is not None
        assert len(qb.quick_summary) > 0

    # Ranks are continuous 1..7
    assert [it.rank_position for it in result.ranked_items] == [1, 2, 3, 4, 5, 6, 7]


def test_extract_quick_summary_bounds_length():
    """Verify that extract_quick_summary extracts up to 3 sentences and truncates cleanly."""
    text = (
        "OpenAI announced a major developer update today. "
        "The new SDK enables parallel coding agents to interact with git repositories. "
        "Developers can now deploy real-time diff engines with sub-millisecond latencies. "
        "A fourth sentence that should be omitted from the 3-sentence summary. "
        "A fifth sentence also omitted."
    )
    summary = extract_quick_summary(text, max_sentences=3, max_chars=300)
    assert "OpenAI announced a major developer update today." in summary
    assert "The new SDK enables parallel coding agents" in summary
    assert "Developers can now deploy real-time diff engines" in summary
    assert "fourth sentence" not in summary
    assert "fifth sentence" not in summary


def test_two_tier_markdown_rendering(db_session: Session):
    """Verify that export_personalized_markdown renders both Featured Deep Dives and In Brief sections."""
    repo = NewsRepository(session=db_session)
    now = datetime.now(timezone.utc)
    b_date = now.date()

    src = repo.sources.create("OpenAI", "openai", "https://openai.com")
    sub = repo.subscribers.create(
        email="reader@example.com",
        name="Alex Reader",
        bio_or_role="AI Dev",
        is_active=True,
    )

    # Create 3 digests: 2 featured, 1 quick bite
    art1 = repo.articles.create(source_id=src.id, external_id="a1", title="Article 1", url="https://oa.com/1", published_at=now)
    art2 = repo.articles.create(source_id=src.id, external_id="a2", title="Article 2", url="https://oa.com/2", published_at=now)
    art3 = repo.articles.create(source_id=src.id, external_id="a3", title="Article 3", url="https://oa.com/3", published_at=now)

    d1 = repo.article_digests.create(article_id=art1.id, title="Title 1", url="https://oa.com/1", source_name="OpenAI", source_type="openai", summary="Summary 1. Half page.")
    d2 = repo.article_digests.create(article_id=art2.id, title="Title 2", url="https://oa.com/2", source_name="OpenAI", source_type="openai", summary="Summary 2. Half page.")
    d3 = repo.article_digests.create(article_id=art3.id, title="Title 3", url="https://oa.com/3", source_name="OpenAI", source_type="openai", summary="Summary 3. Short.")

    repo.user_rankings.create(
        subscriber_id=sub.id,
        digest_id=d1.id,
        rank_position=1,
        rank_score=95.0,
        relevance_reasoning="Reason 1",
        batch_date=b_date,
        tier="featured",
    )
    repo.user_rankings.create(
        subscriber_id=sub.id,
        digest_id=d2.id,
        rank_position=2,
        rank_score=90.0,
        relevance_reasoning="Reason 2",
        batch_date=b_date,
        tier="featured",
    )
    repo.user_rankings.create(
        subscriber_id=sub.id,
        digest_id=d3.id,
        rank_position=3,
        rank_score=80.0,
        relevance_reasoning="Reason 3",
        batch_date=b_date,
        tier="quick_bite",
        quick_summary="A clean 3-line quick summary for article 3.",
    )
    db_session.commit()

    agent = UserRankingAgent(session=db_session, preferred_provider="auto")
    md = agent.export_personalized_markdown("reader@example.com", batch_date=b_date)

    assert "# 🌟 Featured Deep Dives" in md
    assert "Title 1" in md
    assert "Title 2" in md
    assert "# ⚡ In Brief & Ecosystem Radar (Quick Takes)" in md
    assert "Title 3" in md
    assert "A clean 3-line quick summary for article 3." in md



