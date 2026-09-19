"""Drop and recreate all tables defined on Base.metadata.

Gives a clean slate before reseeding. Safe to run repeatedly.

Usage (from backend/):
    python -m scripts.reset_db --yes
    python -m scripts.reset_db            # prompts for confirmation
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.session import Base, engine  # noqa: E402
import app.models  # noqa: E402,F401  (registers all tables on Base.metadata)


async def reset_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    print("Database reset: all tables dropped and recreated.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drop and recreate all tables.")
    parser.add_argument("--yes", action="store_true", help="Skip the confirmation prompt.")
    args = parser.parse_args()

    if not args.yes:
        answer = input("This will DROP ALL TABLES and recreate them. Continue? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return

    asyncio.run(reset_db())


if __name__ == "__main__":
    main()
