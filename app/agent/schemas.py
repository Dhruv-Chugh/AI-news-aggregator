"""Pydantic Schemas for AI News Digest Agent.

Defines the structured output schemas for half-page article & video summaries,
problem statements, solution breakthroughs, and key insights.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ArticleDigestOutput(BaseModel):
    """Structured output returned by the LLM agent for an article or video."""

    title: str = Field(
        ...,
        description="Clear, refined title of the article or video.",
    )
    summary: str = Field(
        ...,
        description=(
            "Comprehensive, knowledge-rich half-page summary (~250-500 words). "
            "It must provide substantial context, conceptual depth, and actionable explanation "
            "rather than superficial bullet points."
        ),
    )
    problem_statement: str = Field(
        ...,
        description=(
            "Detailed description of the core problem, pain point, bottleneck, or industry dilemma "
            "highlighted by the author or speaker."
        ),
    )
    solution_statement: str = Field(
        ...,
        description=(
            "Detailed explanation of the solution, architecture, methodology, innovation, or breakthrough "
            "presented to solve or address the problem."
        ),
    )
    key_insights: List[str] = Field(
        default_factory=list,
        description=(
            "3 to 6 high-value, actionable insights, key facts, mental models, or practical takeaways."
        ),
    )


class DigestResult(BaseModel):
    """Result of processing a single article through the DigestAgent."""

    article_id: int
    title: str
    url: str
    source_name: str
    source_type: str
    category: Optional[str] = None
    output: ArticleDigestOutput
    model_used: str
    tokens_used: Optional[int] = None
    saved_to_db: bool = False
    error: Optional[str] = None


class AgentRunReport(BaseModel):
    """Overall summary report of a DigestAgent execution batch."""

    total_articles: int = 0
    processed: int = 0
    successful: int = 0
    failed: int = 0
    skipped: int = 0
    model_breakdown: Dict[str, int] = Field(default_factory=dict)
    results: List[DigestResult] = Field(default_factory=list)

