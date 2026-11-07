"""AI News Agent Package.

Provides:
- DigestAgent: Synthesizes articles from YouTube, OpenAI, and Anthropic into table 'digest'
- UserRankingAgent: Evaluates, scores, and ranks summaries according to user interest profiles
- RankingSchedulerService: Runs the personalized ranking agent every 24 hours
"""

from app.agent.email_agent import EmailBatchDeliveryReport, EmailDeliveryAgent
from app.agent.llm_client import DualLLMClient, estimate_tokens
from app.agent.ranking_agent import UserRankingAgent
from app.agent.ranking_schemas import (
    CandidateDigestInput,
    PersonalizedRankingOutput,
    RankedDigestItem,
    UserProfileData,
    UserRankingBatchReport,
)
from app.agent.ranking_scheduler import RankingSchedulerService, start_ranking_scheduler
from app.agent.schemas import AgentRunReport, ArticleDigestOutput, DigestResult
from app.agent.summarizer import DigestAgent

__all__ = [
    # Digest Summarizer
    "DigestAgent",
    "DualLLMClient",
    "ArticleDigestOutput",
    "DigestResult",
    "AgentRunReport",
    "estimate_tokens",
    # User Interest Ranking Agent
    "UserRankingAgent",
    "UserProfileData",
    "CandidateDigestInput",
    "RankedDigestItem",
    "PersonalizedRankingOutput",
    "UserRankingBatchReport",
    # 24-Hour Scheduler
    "RankingSchedulerService",
    "start_ranking_scheduler",
    # Email Delivery Agent
    "EmailDeliveryAgent",
    "EmailBatchDeliveryReport",
]
