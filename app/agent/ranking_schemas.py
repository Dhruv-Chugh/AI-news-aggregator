"""Schemas for Personalized User Interest Ranking Agent.

Defines models for user interest profiles, candidate digest evaluations,
individual item ranking metrics, and batch reporting.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class UserProfileData(BaseModel):
    """User profile and interests used to personalize and rank news digests."""

    subscriber_id: int
    email: str
    name: Optional[str] = None
    bio_or_role: Optional[str] = Field(
        default="AI Engineer & Practitioner",
        description="Role, profession, or background of the user (e.g. AI Researcher, Founder, ML Engineer).",
    )
    expertise_level: str = Field(
        default="intermediate",
        description="Technical depth: 'beginner', 'intermediate', 'advanced', or 'expert'.",
    )
    interests: List[str] = Field(
        default_factory=list,
        description="Key topics, keywords, and domain interests (e.g. 'LLM reasoning', 'robotics', 'agents').",
    )
    preferred_sources: List[str] = Field(
        default_factory=list,
        description="Preferred sources or platforms (e.g. 'youtube', 'openai', 'anthropic').",
    )
    ranking_instructions: Optional[str] = Field(
        default=None,
        description="Custom prioritization rules (e.g. 'Prioritize deep technical breakthroughs over business acquisitions').",
    )


class CandidateDigestInput(BaseModel):
    """Candidate digest item retrieved from table 'digest'."""

    digest_id: int
    article_id: int
    title: str
    url: str
    source_name: str
    source_type: str
    category: Optional[str] = None
    summary: str
    problem_statement: Optional[str] = None
    solution_statement: Optional[str] = None
    key_insights: List[str] = Field(default_factory=list)
    model_used: str = ""
    tokens_used: Optional[int] = None


class RankedDigestItem(BaseModel):
    """A digest item scored, evaluated, and ranked for a specific user."""

    digest_id: int = Field(..., description="ID from table 'digest'")
    title: str = Field(..., description="Article title")
    url: str = Field(..., description="Original article/video URL")
    rank_position: int = Field(..., description="Rank priority position: 1 = highest recommendation")
    rank_score: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Numerical relevance score between 0.0 and 100.0 based on user profile alignment",
    )
    relevance_reasoning: str = Field(
        ...,
        description="Personalized rationale detailing why this article was scored and ranked here for this user.",
    )
    personalized_takeaways: List[str] = Field(
        default_factory=list,
        description="2 to 4 actionable takeaways tailored specifically to this user's domain and role.",
    )
    source_name: Optional[str] = Field(default=None, description="Name of the content source")
    source_type: Optional[str] = Field(default=None, description="Source type: 'youtube', 'openai', 'anthropic'")
    tier: str = Field(
        default="featured",
        description="Display tier: 'featured' (deep half-page dive) or 'quick_bite' (3-4 line compact brief)",
    )
    quick_summary: Optional[str] = Field(
        default=None,
        description="Concise 3-4 line summary formatted for quick radar scanning",
    )


class PersonalizedRankingOutput(BaseModel):
    """Structured response from LLM ranking agent for a user profile."""

    executive_summary: str = Field(
        ...,
        description="A concise 2-3 sentence executive briefing summarizing today's key theme for the user.",
    )
    ranked_items: List[RankedDigestItem] = Field(
        ...,
        description="Sorted list of ranked digest items (rank_position 1 to N).",
    )


class UserRankingBatchReport(BaseModel):
    """Execution summary for a 24-hour personalized ranking cycle."""

    batch_date: str
    executed_at: str
    subscribers_evaluated: int = 0
    total_digests_available: int = 0
    rankings_stored: int = 0
    rankings_by_subscriber: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)

