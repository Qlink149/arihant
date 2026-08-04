"""
Generate a multi-tenant API key for public lead intake.
Prints the plaintext key ONCE; only the SHA-256 hash is stored in MongoDB.

Run from backend/:
  python scripts/generate_api_key.py --project-name "Mélange" --client-name "Melange Website"
  python scripts/generate_api_key.py --project-name "Mélange" --client-name "Melange Website" --rate-limit 60

Requires: MONGO_URL, DB_NAME in backend/.env
"""
from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))
load_dotenv(BACKEND_ROOT / ".env")


async def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a lead-intake API key")
    parser.add_argument("--project-name", required=True, help='Registry project name, e.g. "Mélange"')
    parser.add_argument("--client-name", required=True, help="Label for who holds this key")
    parser.add_argument("--rate-limit", type=int, default=60, help="Requests per minute (default 60)")
    args = parser.parse_args()

    if not os.environ.get("MONGO_URL") or not os.environ.get("DB_NAME"):
        print("ERROR: Set MONGO_URL and DB_NAME")
        sys.exit(1)

    from crm.services.api_key_service import create_api_key

    try:
        result = await create_api_key(
            project_name=args.project_name,
            client_name=args.client_name,
            rate_limit_per_min=args.rate_limit,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: Failed to create API key: {e}")
        sys.exit(1)

    print("API key created. Store the plaintext key securely — it will not be shown again.")
    print(f"  id:                 {result['id']}")
    print(f"  project:            {result['project_name']} ({result['project_id']})")
    print(f"  client:             {result['client_name']}")
    print(f"  rate_limit_per_min: {result['rate_limit_per_min']}")
    print(f"  key_prefix:         {result['key_prefix']}…")
    print()
    print(f"PLAINTEXT_KEY={result['plaintext_key']}")


if __name__ == "__main__":
    asyncio.run(main())
