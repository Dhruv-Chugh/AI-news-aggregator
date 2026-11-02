"""Markdown Export Service (OOP & Pydantic).

Serializes scraped OpenAI articles, Anthropic articles, YouTube videos, and daily aggregated digests
into clean, publication-ready GitHub-Flavored Markdown (.md) documents.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Union

from app.models.anthropic import AnthropicArticle
from app.models.openai import OpenAIArticle
from app.models.youtube import YouTubeVideo

logger = logging.getLogger("ai_news.markdown_exporter")


class MarkdownExporter:
    """Service to export articles, videos, and multi-source digests to Markdown."""

    def __init__(self, default_output_dir: Union[str, Path] = "exports") -> None:
        self.output_dir = Path(default_output_dir)

    def export_openai_articles(
        self,
        articles: List[OpenAIArticle],
        title: str = "OpenAI News & Research Digest",
        subtitle: Optional[str] = None,
    ) -> str:
        """Export a list of OpenAI articles into a cohesive Markdown document."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        total = len(articles)

        research_count = sum(1 for a in articles if a.is_research)
        eng_count = sum(1 for a in articles if a.is_engineering)
        other_count = total - (research_count + eng_count)

        lines: List[str] = [
            f"# {title}",
            "",
            f"> **Generated:** `{now_str}` | **Total Articles:** `{total}`",
            f"> **Breakdown:** `{research_count}` Research, `{eng_count}` Engineering, `{other_count}` Other",
        ]

        if subtitle:
            lines.extend(["", subtitle])

        lines.extend(["", "---", ""])

        if not articles:
            lines.append("_No articles found matching the specified timeframe and criteria._\n")
            return "\n".join(lines)

        research_items = [a for a in articles if a.is_research]
        engineering_items = [a for a in articles if a.is_engineering]
        other_items = [a for a in articles if not a.is_research and not a.is_engineering]

        index = 1
        if research_items:
            lines.extend(["## 🔬 Research Focus", ""])
            for art in research_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                lines.append(f"- **Category:** `{art.primary_category}`")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Author:** {art.author}")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Abstract / Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        if engineering_items:
            lines.extend(["## ⚙️ Engineering & Infrastructure", ""])
            for art in engineering_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                lines.append(f"- **Category:** `{art.primary_category}`")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Author:** {art.author}")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        if other_items:
            lines.extend(["## 📢 Product & Company Announcements", ""])
            for art in other_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                cats_str = ", ".join(f"`{c}`" for c in art.categories) if art.categories else "`General`"
                lines.append(f"- **Categories:** {cats_str}")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        return "\n".join(lines).strip()

    def export_anthropic_articles(
        self,
        articles: List[AnthropicArticle],
        title: str = "Anthropic News & Research Digest",
        subtitle: Optional[str] = None,
    ) -> str:
        """Export a list of Anthropic articles into a cohesive Markdown document."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        total = len(articles)

        research_count = sum(1 for a in articles if a.is_research)
        eng_count = sum(1 for a in articles if a.is_engineering)
        news_count = sum(1 for a in articles if a.is_news)

        lines: List[str] = [
            f"# {title}",
            "",
            f"> **Generated:** `{now_str}` | **Total Articles:** `{total}`",
            f"> **Breakdown:** `{research_count}` Research, `{eng_count}` Engineering, `{news_count}` News",
        ]

        if subtitle:
            lines.extend(["", subtitle])

        lines.extend(["", "---", ""])

        if not articles:
            lines.append("_No Anthropic articles found matching the specified timeframe and criteria._\n")
            return "\n".join(lines)

        research_items = [a for a in articles if a.is_research]
        engineering_items = [a for a in articles if a.is_engineering]
        news_items = [a for a in articles if not a.is_research and not a.is_engineering]

        index = 1
        if research_items:
            lines.extend(["## 🔬 Research Focus", ""])
            for art in research_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                lines.append(f"- **Categories:** {', '.join(f'`{c}`' for c in art.categories)}")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Author:** {art.author}")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Abstract / Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        if engineering_items:
            lines.extend(["## ⚙️ Engineering & Architecture", ""])
            for art in engineering_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                lines.append(f"- **Categories:** {', '.join(f'`{c}`' for c in art.categories)}")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Author:** {art.author}")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        if news_items:
            lines.extend(["## 📢 News & Announcements", ""])
            for art in news_items:
                lines.append(f"### {index}. [{art.title}]({art.url})")
                cats_str = ", ".join(f"`{c}`" for c in art.categories) if art.categories else "`News`"
                lines.append(f"- **Categories:** {cats_str}")
                lines.append(f"- **Published:** `{art.published_at.strftime('%Y-%m-%d %H:%M UTC')}`")
                lines.append(f"- **Author:** {art.author}")
                lines.append(f"- **Source Link:** [{art.url}]({art.url})")
                lines.append("")
                if art.has_full_content and art.content:
                    w_cnt = art.word_count or len(art.content.split())
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(art.content)
                else:
                    lines.append("#### Summary")
                    lines.append(f"> {art.summary}" if art.summary else "> _No summary provided._")
                lines.append("")
                lines.append("---")
                lines.append("")
                index += 1

        return "\n".join(lines).strip()

    def export_youtube_videos(
        self,
        videos: List[YouTubeVideo],
        title: str = "YouTube Video Digest",
    ) -> str:
        """Export a list of YouTube videos and transcripts into Markdown."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        total = len(videos)

        lines: List[str] = [
            f"# {title}",
            "",
            f"> **Generated:** `{now_str}` | **Total Videos:** `{total}`",
            "",
            "---",
            "",
        ]

        if not videos:
            lines.append("_No videos found matching the specified timeframe._\n")
            return "\n".join(lines)

        for idx, v in enumerate(videos, 1):
            pub_str = v.published_at.strftime("%Y-%m-%d %H:%M UTC")
            vformat = "Short" if v.is_short else "Full Video"

            lines.append(f"## {idx}. [{v.title}]({v.url})")
            lines.append(f"- **Channel:** {v.channel_name} (`{v.channel_id}`)")
            lines.append(f"- **Published:** `{pub_str}`")
            lines.append(f"- **Format:** `{vformat}`")
            lines.append(f"- **Watch URL:** [{v.url}]({v.url})")
            lines.append("")

            if v.description:
                preview = v.description[:350].strip().replace("\n", " ")
                lines.append("### Description")
                lines.append(f"> {preview}...")
                lines.append("")

            if v.transcript and v.transcript.available:
                lines.append(
                    f"### Transcript Knowledge ({v.transcript.word_count:,} words, {v.transcript.language})"
                )
                preview = v.transcript.text[:600].strip()
                lines.append(f"> {preview}...")
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines).strip()

    def export_unified_digest(
        self,
        openai_articles: Optional[List[OpenAIArticle]] = None,
        anthropic_articles: Optional[List[AnthropicArticle]] = None,
        videos: Optional[List[YouTubeVideo]] = None,
        articles: Optional[List[OpenAIArticle]] = None,  # Backward compatibility
        title: str = "Daily AI News Digest",
        include_full_content: bool = False,
    ) -> str:
        """Export a unified daily digest containing OpenAI, Anthropic, and YouTube updates."""
        now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        oai_list = openai_articles or articles or []
        anthropic_list = anthropic_articles or []
        vid_list = videos or []

        oai_count = len(oai_list)
        anthropic_count = len(anthropic_list)
        vid_count = len(vid_list)

        lines: List[str] = [
            f"# {title}",
            "",
            f"> **Date:** `{now_str}`",
            (
                f"> **Aggregated Sources:** `{oai_count}` OpenAI Post(s) | "
                f"`{anthropic_count}` Anthropic Post(s) | `{vid_count}` YouTube Video(s)"
            ),
            "",
            "---",
            "",
        ]

        if anthropic_list:
            lines.append("## 🔮 Anthropic News, Research & Engineering")
            lines.append("")
            for idx, a in enumerate(anthropic_list, 1):
                lines.append(f"### {idx}. [{a.title}]({a.url})")
                lines.append(
                    f"- **Category:** `{a.primary_category}` | "
                    f"**Published:** `{a.published_at.strftime('%Y-%m-%d %H:%M UTC')}`"
                )
                lines.append(f"- **Link:** [{a.url}]({a.url})")
                if include_full_content and a.has_full_content and a.content:
                    w_cnt = a.word_count or len(a.content.split())
                    lines.append("")
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(a.content)
                elif a.summary:
                    lines.append(f"> {a.summary}")
                lines.append("")

            lines.append("---")
            lines.append("")

        if oai_list:
            lines.append("## 📰 OpenAI News, Research & Engineering")
            lines.append("")
            for idx, a in enumerate(oai_list, 1):
                lines.append(f"### {idx}. [{a.title}]({a.url})")
                lines.append(
                    f"- **Category:** `{a.primary_category}` | "
                    f"**Published:** `{a.published_at.strftime('%Y-%m-%d %H:%M UTC')}`"
                )
                lines.append(f"- **Link:** [{a.url}]({a.url})")
                if include_full_content and a.has_full_content and a.content:
                    w_cnt = a.word_count or len(a.content.split())
                    lines.append("")
                    lines.append(f"#### Full Article Content ({w_cnt:,} words)")
                    lines.append(a.content)
                elif a.summary:
                    lines.append(f"> {a.summary}")
                lines.append("")

            lines.append("---")
            lines.append("")

        if vid_list:
            lines.append("## 🎥 YouTube Videos & Insights")
            lines.append("")
            for idx, v in enumerate(vid_list, 1):
                lines.append(f"### {idx}. [{v.title}]({v.url})")
                lines.append(
                    f"- **Channel:** {v.channel_name} | "
                    f"**Published:** `{v.published_at.strftime('%Y-%m-%d %H:%M UTC')}`"
                )
                lines.append(f"- **Watch Link:** [{v.url}]({v.url})")
                if v.transcript and v.transcript.available:
                    lines.append(
                        f"> **Transcript Preview ({v.transcript.word_count:,} words):** {v.transcript.text[:300]}..."
                    )
                lines.append("")

            lines.append("---")
            lines.append("")

        return "\n".join(lines).strip()

    def save_to_file(self, content: str, filepath: Union[str, Path]) -> Path:
        """Write markdown content to a file, automatically creating parent directories."""
        dest = Path(filepath)
        if not dest.is_absolute():
            # If path doesn't already start with the output_dir name, prepend it
            if not dest.parts or dest.parts[0] != self.output_dir.name:
                dest = self.output_dir / dest

        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(content, encoding="utf-8")
        logger.info("Exported markdown file to: %s", dest.resolve())
        return dest.resolve()
