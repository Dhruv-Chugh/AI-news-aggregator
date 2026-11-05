"""Ingest latest Anthropic articles into database so DB contains entries for all 3 scrapers."""

import logging
from app.database import NewsRepository
from app.scrapers.anthropic import AnthropicScraperService

logging.basicConfig(level=logging.INFO)

print("Fetching latest 2 Anthropic articles with full web content...")
with AnthropicScraperService() as ant:
    articles = ant.get_articles(limit=2, fetch_full_content=True)
    print(f"Retrieved {len(articles)} Anthropic articles.")

    with NewsRepository() as repo:
        for a in articles:
            db_art, is_new = repo.save_anthropic_article(a)
            status = "Created" if is_new else "Updated"
            print(f"[{status}] {db_art.title} ({db_art.word_count} words)")

print("Done! Database now has entries for all 3 scrapers (YouTube, OpenAI, Anthropic).")

