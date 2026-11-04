"""CLI entry point to create and initialize database tables for AI News Aggregator."""

from app.database.init_db import create_tables, init_db, main, seed_initial_data

if __name__ == "__main__":
    main()
