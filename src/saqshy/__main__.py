"""
SAQSHY Bot Entry Point

Allows running the bot with: python -m saqshy
"""

import asyncio
import sys

import structlog

from saqshy.app import create_app, run_app

logger = structlog.get_logger(__name__)


def main() -> int:
    """Main entry point for the SAQSHY bot."""
    try:
        logger.info("starting_saqshy_bot", version="2.0.0")
        asyncio.run(run_app(create_app()))
        return 0
    except KeyboardInterrupt:
        logger.info("shutdown_requested")
        return 0
    except Exception as e:
        logger.exception("fatal_error", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(main())
