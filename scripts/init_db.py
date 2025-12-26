#!/usr/bin/env python3
"""
Initialize SAQSHY Database

Creates all database tables and required extensions.
Run this before starting the application for the first time.

Usage:
    python scripts/init_db.py

Or with custom database URL:
    DATABASE_URL=postgresql://... python scripts/init_db.py
"""

import asyncio
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from saqshy.config import get_settings
from saqshy.db import models  # noqa: F401 - Import to register models
from saqshy.db.database import Base

logger = structlog.get_logger(__name__)


async def create_extensions(engine) -> None:
    """Create required PostgreSQL extensions."""
    extensions = [
        "uuid-ossp",  # For UUID generation
    ]

    async with engine.begin() as conn:
        for ext in extensions:
            try:
                await conn.execute(text(f'CREATE EXTENSION IF NOT EXISTS "{ext}"'))
                logger.info("extension_created", extension=ext)
            except Exception as e:
                logger.warning(
                    "extension_creation_failed",
                    extension=ext,
                    error=str(e),
                )


async def create_tables(engine) -> None:
    """Create all database tables."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    logger.info("tables_created")


async def verify_connection(engine) -> bool:
    """Verify database connection."""
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            result.fetchone()
        return True
    except Exception as e:
        logger.error("connection_failed", error=str(e))
        return False


async def main() -> int:
    """Main initialization function."""
    logger.info("starting_database_initialization")

    # Get settings
    try:
        settings = get_settings()
        database_url = settings.database.url.get_secret_value()
    except Exception as e:
        logger.error("settings_load_failed", error=str(e))
        print("\nError: Could not load settings. Make sure .env file exists.")
        print("Copy .env.example to .env and configure DATABASE_URL.")
        return 1

    # Ensure asyncpg driver
    if database_url.startswith("postgresql://"):
        database_url = database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    logger.info("connecting_to_database")

    # Create engine
    try:
        engine = create_async_engine(
            database_url,
            echo=True,  # Show SQL for debugging
        )
    except Exception as e:
        logger.error("engine_creation_failed", error=str(e))
        return 1

    # Verify connection
    if not await verify_connection(engine):
        print("\nError: Could not connect to database.")
        print("Verify DATABASE_URL and ensure PostgreSQL is running.")
        return 1

    logger.info("connection_verified")

    # Create extensions
    await create_extensions(engine)

    # Create tables
    try:
        await create_tables(engine)
    except Exception as e:
        logger.error("table_creation_failed", error=str(e))
        return 1

    # Cleanup
    await engine.dispose()

    logger.info("database_initialization_complete")
    print("\nDatabase initialization complete!")
    print("Tables created successfully.")

    return 0


if __name__ == "__main__":
    # Configure structlog for console output
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    exit_code = asyncio.run(main())
    sys.exit(exit_code)
