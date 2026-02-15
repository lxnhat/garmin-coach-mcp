"""CLI entrypoints for garmin-coach-mcp.

  garmin-coach-auth   — authenticate with Garmin Connect (saves tokens)
  garmin-coach-sync   — sync data from Garmin to local SQLite
  garmin-coach-mcp    — start the MCP server (stdio)
"""

from __future__ import annotations

import argparse
import json
import os
import sys

DEFAULT_DB = os.path.expanduser("~/.garminconnect/garmin_coach.db")
DEFAULT_TOKEN_DIR = os.path.expanduser("~/.garminconnect")


# ── garmin-coach-auth ────────────────────────────────────────────────────────


def cmd_auth():
    """Authenticate with Garmin Connect and save tokens."""
    parser = argparse.ArgumentParser(
        prog="garmin-coach-auth",
        description="Authenticate with Garmin Connect (supports MFA).",
    )
    parser.add_argument("--email", help="Garmin email (or set GARMIN_EMAIL)")
    parser.add_argument("--password", help="Garmin password (or set GARMIN_PASSWORD)")
    parser.add_argument(
        "--token-dir", default=DEFAULT_TOKEN_DIR,
        help=f"Directory to save tokens (default: {DEFAULT_TOKEN_DIR})",
    )
    args = parser.parse_args()

    from .auth import login_interactive

    try:
        client = login_interactive(
            email=args.email,
            password=args.password,
            token_dir=args.token_dir,
        )
        name = getattr(client, "display_name", None) or "Unknown"
        print(f"Authenticated as: {name}")
        print(f"Tokens saved to: {args.token_dir}")
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


# ── garmin-coach-sync ────────────────────────────────────────────────────────


def cmd_sync():
    """Sync Garmin data to local SQLite database."""
    parser = argparse.ArgumentParser(
        prog="garmin-coach-sync",
        description="Sync Garmin Connect data to a local SQLite database.",
    )
    parser.add_argument(
        "--days", type=int, default=30,
        help="Number of days to sync (default: 30)",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--token-dir", default=DEFAULT_TOKEN_DIR,
        help=f"Directory with saved tokens (default: {DEFAULT_TOKEN_DIR})",
    )
    args = parser.parse_args()

    from .auth import login_from_tokens
    from .models import init_db
    from .sync import sync_all

    # Authenticate
    try:
        client = login_from_tokens(args.token_dir)
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        print("Run garmin-coach-auth first.", file=sys.stderr)
        sys.exit(1)

    # Init DB
    session = init_db(args.db)

    # Sync
    print(f"Syncing {args.days} days to {args.db} ...")
    result = sync_all(client, session, days=args.days)
    print(json.dumps(result, indent=2))

    if result.get("warnings"):
        print(f"\n{len(result['warnings'])} warning(s) — see details above.", file=sys.stderr)


# ── garmin-coach-mcp ─────────────────────────────────────────────────────────


def cmd_server():
    """Start the Garmin Coach MCP server (stdio transport)."""
    parser = argparse.ArgumentParser(
        prog="garmin-coach-mcp",
        description="Start the Garmin Coach MCP server (stdio).",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()

    # Set DB path for the server module to pick up
    os.environ["GARMIN_COACH_DB"] = args.db

    from .server import mcp

    print(f"Starting Garmin Coach MCP server (db: {args.db})", file=sys.stderr)
    mcp.run()
