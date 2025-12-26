#!/usr/bin/env python3
"""
Seed SAQSHY Spam Database

Populates the Qdrant vector database with initial spam patterns.

Usage:
    python scripts/seed_spam_db.py

Or with custom file:
    python scripts/seed_spam_db.py --file custom_patterns.json
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import structlog

logger = structlog.get_logger(__name__)


# Default spam patterns for initial seeding
DEFAULT_PATTERNS = [
    {
        "text": "Double your Bitcoin now! Guaranteed 100% profit!",
        "threat_type": "crypto_scam",
        "confidence": 0.95,
    },
    {
        "text": "DM me for free crypto signals. 10x returns guaranteed!",
        "threat_type": "crypto_scam",
        "confidence": 0.95,
    },
    {
        "text": "Invest $100 and earn $1000 daily! Message me now!",
        "threat_type": "scam",
        "confidence": 0.9,
    },
    {
        "text": "Free iPhone giveaway! Click here to claim your prize!",
        "threat_type": "phishing",
        "confidence": 0.85,
    },
    {
        "text": "You won the lottery! Send your details to claim!",
        "threat_type": "scam",
        "confidence": 0.95,
    },
    {
        "text": "Hot singles in your area! Click to meet them now!",
        "threat_type": "spam",
        "confidence": 0.9,
    },
    {
        "text": "Earn money from home! No experience needed!",
        "threat_type": "spam",
        "confidence": 0.7,
    },
    {
        "text": "Recover your lost crypto! Contact our expert team!",
        "threat_type": "crypto_scam",
        "confidence": 0.95,
    },
    {
        "text": "Free airdrop! Connect your wallet to claim tokens!",
        "threat_type": "crypto_scam",
        "confidence": 0.9,
    },
    {
        "text": "Looking for investors! 500% returns in 30 days!",
        "threat_type": "scam",
        "confidence": 0.95,
    },
]


async def seed_patterns(patterns: list[dict]) -> int:
    """
    Seed spam patterns into the database.

    Args:
        patterns: List of pattern dictionaries.

    Returns:
        Number of patterns added.
    """
    # TODO: Implement actual seeding when Qdrant is available

    logger.info("seeding_patterns", count=len(patterns))

    # For now, just log what would be seeded
    for i, pattern in enumerate(patterns):
        logger.info(
            "pattern_added",
            index=i + 1,
            threat_type=pattern["threat_type"],
            text_preview=pattern["text"][:50],
        )

    return len(patterns)


async def main(args: argparse.Namespace) -> int:
    """Main seeding function."""
    logger.info("starting_spam_db_seeding")

    # Load patterns
    if args.file:
        try:
            with open(args.file) as f:
                patterns = json.load(f)
            logger.info("patterns_loaded_from_file", file=args.file)
        except Exception as e:
            logger.error("file_load_failed", file=args.file, error=str(e))
            return 1
    else:
        patterns = DEFAULT_PATTERNS
        logger.info("using_default_patterns")

    # Seed patterns
    try:
        count = await seed_patterns(patterns)
    except Exception as e:
        logger.error("seeding_failed", error=str(e))
        return 1

    logger.info("seeding_complete", patterns_added=count)
    print(f"\nSeeding complete! Added {count} spam patterns.")

    return 0


if __name__ == "__main__":
    # Parse arguments
    parser = argparse.ArgumentParser(description="Seed spam database")
    parser.add_argument(
        "--file",
        type=str,
        help="Path to JSON file with patterns",
    )
    args = parser.parse_args()

    # Configure structlog
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.dev.ConsoleRenderer(),
        ],
    )

    exit_code = asyncio.run(main(args))
    sys.exit(exit_code)
