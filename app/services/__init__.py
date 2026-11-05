"""Application business services."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.services.content_extractor import ArticleContentExtractor, ExtractedContent
    from app.services.llm_formatter import (
        LLMMarkdownFormatter,
        format_article_for_llm,
        format_articles_for_llm,
        get_database_llm_markdown,
    )
    from app.services.transcript_service import (
        TranscriptCleaner,
        TranscriptIdParser,
        TranscriptService,
    )

__all__ = [
    "TranscriptService",
    "TranscriptIdParser",
    "TranscriptCleaner",
    "ArticleContentExtractor",
    "ExtractedContent",
    "LLMMarkdownFormatter",
    "format_article_for_llm",
    "format_articles_for_llm",
    "get_database_llm_markdown",
]


def __getattr__(name: str):
    """Lazy import services to prevent circular imports and runpy warnings."""
    if name in ("TranscriptService", "TranscriptIdParser", "TranscriptCleaner"):
        import app.services.transcript_service as mod
        return getattr(mod, name)
    if name in ("ArticleContentExtractor", "ExtractedContent"):
        import app.services.content_extractor as mod
        return getattr(mod, name)
    if name in (
        "LLMMarkdownFormatter",
        "format_article_for_llm",
        "format_articles_for_llm",
        "get_database_llm_markdown",
    ):
        import app.services.llm_formatter as mod
        return getattr(mod, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
