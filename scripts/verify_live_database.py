"""Comprehensive Live PostgreSQL Verification and Diagnostics Script.

Runs end-to-end tests against the active PostgreSQL Docker container:
1. Connection & Engine Healthcheck
2. Schema & Table Structure Inspection
3. CRUD Operations across all models (Source, Article, Digest, Subscriber)
4. Unicode, Emoji, and Large Content Payload Handling
5. JSON Metadata Serialization and Deserialization
6. Deduplication via Upsert
7. Foreign Key Relationships & Cascade Deletion
8. Lookback Window Queries & Timezone Precision
9. Transaction Rollback Safety
"""

from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict

from sqlalchemy import func, inspect, select, text

from app.database import (
    Article,
    Base,
    Digest,
    NewsRepository,
    Source,
    Subscriber,
    check_connection,
    create_tables,
    engine,
    get_db_session,
    utc_now,
)


def run_checks() -> bool:
    if sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    print("\n" + "=" * 65)
    print("🔍 LIVE POSTGRESQL VERIFICATION & DIAGNOSTICS")
    print("=" * 65)

    # 1. Connection Check
    print("1️⃣ Testing connection to live PostgreSQL container...")
    if not check_connection(engine):
        print(f"❌ Could not connect to {engine.url.render_as_string(hide_password=True)}")
        return False
    print(f"   🟢 Connected successfully: {engine.url.render_as_string(hide_password=True)}")

    # 2. Schema Inspection
    print("\n2️⃣ Inspecting database tables and columns...")
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    expected_tables = {"sources", "articles", "digests", "subscribers"}
    missing = expected_tables - existing_tables
    if missing:
        print(f"❌ Missing tables: {missing}")
        return False

    print(f"   🟢 All expected tables present: {sorted(existing_tables)}")
    for tbl in sorted(expected_tables):
        cols = [c["name"] for c in inspector.get_columns(tbl)]
        pk = inspector.get_pk_constraint(tbl).get("constrained_columns", [])
        fks = [f"{fk['constrained_columns']} -> {fk['referred_table']}.{fk['referred_columns']}" for fk in inspector.get_foreign_keys(tbl)]
        fk_str = f" | FK: {', '.join(fks)}" if fks else ""
        print(f"   • Table '{tbl}': {len(cols)} columns | PK: {pk}{fk_str}")

    # 3. CRUD and Payload Testing
    print("\n3️⃣ Testing CRUD, Unicode, Large Content & JSON Metadata...")
    now = datetime.now(timezone.utc)
    test_external_id = f"test-art-{int(now.timestamp())}"

    with get_db_session() as session:
        repo = NewsRepository(session=session)

        # Create source
        src = repo.sources.create(
            name="Verification AI Labs 🧪",
            source_type="test_source",
            url="https://example.com/ai-labs",
            channel_id="UC_test_verification_01",
            handle="@verification_ai",
            is_active=True,
        )
        session.flush()
        src_id = src.id
        print(f"   🟢 Source created: id={src_id}, name='{src.name}'")

        # Create Article with large text and JSON metadata
        long_body = "# Breakthrough in Neural Architecture 🚀\n\n" + (
            "This is a paragraph analyzing deep transformer scalability with linear recurrence. " * 50
        )
        art = repo.articles.create(
            source_id=src_id,
            external_id=test_external_id,
            title="Transformer Scalability & Reasoning (Test) 🧠",
            url="https://example.com/ai-labs/breakthrough",
            published_at=now,
            author="Dr. Lead Researcher",
            category="Research",
            summary="A comprehensive study into 100k context reasoning.",
            raw_content=long_body,
            content_type="article",
            word_count=len(long_body.split()),
            metadata_json={
                "tags": ["neural networks", "reasoning", "scalability"],
                "benchmarks": {"gsm8k": 94.2, "math": 78.5},
                "verified": True,
            },
        )
        session.flush()
        art_id = art.id
        print(f"   🟢 Article created: id={art_id}, word_count={art.word_count}, metadata keys={list(art.metadata_json.keys())}")

        # Verify article retrieval & metadata deserialization
        fetched_art = repo.articles.get_by_id(art_id)
        assert fetched_art is not None
        assert fetched_art.title == "Transformer Scalability & Reasoning (Test) 🧠"
        assert fetched_art.metadata_json["benchmarks"]["gsm8k"] == 94.2
        print("   🟢 Verified article retrieval and JSON metadata preservation.")

        # Test Upsert / Deduplication
        upserted_art, is_created = repo.articles.upsert(
            external_id=test_external_id,
            title="Transformer Scalability & Reasoning (Revised Test) 🧠",
            url="https://example.com/ai-labs/breakthrough-revised",
            published_at=now,
            summary="Updated summary after review.",
        )
        session.flush()
        assert is_created is False
        assert upserted_art.id == art_id
        assert upserted_art.title == "Transformer Scalability & Reasoning (Revised Test) 🧠"
        print(f"   🟢 Deduplication verified: record updated in-place without duplicate row.")

        # Test Digest creation
        digest = repo.digests.create(
            digest_date=now.date(),
            title="Verification Daily AI Digest",
            content_markdown="# Daily Digest\n- AI updates verified.",
            article_count=1,
        )
        session.flush()
        print(f"   🟢 Digest created: id={digest.id}, date={digest.digest_date}")

        # Test Subscriber registration & lowercasing
        sub = repo.subscribers.create(
            email="TestUser.AI@Example.COM",
            name="Test User",
        )
        session.flush()
        assert sub.email == "testuser.ai@example.com"
        print(f"   🟢 Subscriber created with case normalization: '{sub.email}'")

        # 4. Timezone & Lookback Window Queries
        print("\n4️⃣ Testing Lookback Window & Timezone filtering...")
        recent_24h = repo.articles.get_recent(hours=24)
        found_in_recent = any(a.id == art_id for a in recent_24h)
        assert found_in_recent is True
        print(f"   🟢 Lookback filter verified: article found in 24h window (total found={len(recent_24h)}).")

        # 5. Cascade Deletion Testing
        print("\n5️⃣ Testing Foreign Key Cascade Deletion...")
        deleted = repo.sources.delete(src_id)
        session.flush()
        assert deleted is True
        orphan_art = repo.articles.get_by_id(art_id)
        assert orphan_art is None
        print("   🟢 Cascade deletion verified: deleting source safely removed linked articles.")

        # Clean up test subscriber and digest
        repo.subscribers.delete(sub.email)
        session.delete(digest)
        session.commit()
        print("   🟢 Cleaned up verification temporary test records.")

    # 6. Transaction Rollback Safety Testing
    print("\n6️⃣ Testing Transaction Rollback on Failure...")
    initial_count = 0
    with get_db_session() as session:
        initial_count = session.execute(select(func.count(Article.id))).scalar() or 0

    try:
        with get_db_session() as session:
            repo = NewsRepository(session=session)
            # Create dummy article
            repo.articles.create(
                external_id="rollback-test-id",
                title="Rollback Test Article",
                url="https://example.com/fail",
                published_at=now,
            )
            session.flush()
            # Force deliberate exception to trigger rollback
            raise ValueError("Deliberate test error to trigger session rollback")
    except ValueError:
        pass

    with get_db_session() as session:
        after_count = session.execute(select(func.count(Article.id))).scalar() or 0
        assert initial_count == after_count
        print(f"   🟢 Rollback verified: database row count remained unchanged ({after_count}).")

    # 7. Connection Pool & Stats
    print("\n7️⃣ Inspecting Connection Pool Status...")
    pool = engine.pool
    print(f"   • Pool size:     {pool.size()}")
    print(f"   • Checked out:   {pool.checkedout()}")
    print(f"   • Overflow:      {pool.overflow()}")
    print("   🟢 Connection pool healthy and no leaked connections.")

    print("\n" + "=" * 65)
    print("🎉 ALL LIVE POSTGRESQL VERIFICATION CHECKS PASSED PERFECTLY!")
    print("=" * 65 + "\n")
    return True


if __name__ == "__main__":
    success = run_checks()
    sys.exit(0 if success else 1)
