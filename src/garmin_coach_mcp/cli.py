"""CLI entrypoints for garmin-coach-mcp.

  garmin-coach-auth      — authenticate with Garmin Connect (saves tokens)
  garmin-coach-sync      — sync data from Garmin to local SQLite
  garmin-coach-summary   — print health + training summary (human-readable)
  garmin-coach-query     — run read-only SQL and print results
  garmin-coach-mcp       — start the MCP server (stdio)
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
    parser.add_argument("--mfa-code", help="MFA code (if MFA is required)")
    parser.add_argument(
        "--token-dir", default=DEFAULT_TOKEN_DIR,
        help=f"Directory to save tokens (default: {DEFAULT_TOKEN_DIR})",
    )
    args = parser.parse_args()

    from .auth import login

    # login() handles exit codes: 1 for errors, 2 for MFA required
    client = login(
        email=args.email,
        password=args.password,
        mfa_code=args.mfa_code,
        token_dir=args.token_dir,
    )
    name = getattr(client, "display_name", None) or "Unknown"
    print(f"Authenticated as: {name}")
    print(f"Tokens saved to: {args.token_dir}")


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


# ── garmin-coach-summary ──────────────────────────────────────────────────────


def cmd_summary():
    """Print a human-readable health + training summary."""
    parser = argparse.ArgumentParser(
        prog="garmin-coach-summary",
        description="Print a health and training summary from the local Garmin database.",
    )
    parser.add_argument(
        "--days", type=int, default=7,
        help="Number of days to summarize (default: 7)",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        print("Error: No Garmin database found. Run garmin-coach-sync first.", file=sys.stderr)
        sys.exit(1)

    os.environ["GARMIN_COACH_DB"] = args.db

    from .server import health_summary, training_overview, sync_status

    # Health summary
    hs = health_summary.fn(days=args.days)
    print(f"=== Health Summary (last {args.days} days) ===\n")

    if hs["daily"]:
        print("Daily Stats:")
        for d in hs["daily"]:
            parts = [f"  {d['date']}:"]
            if d.get("steps"):
                parts.append(f"{d['steps']} steps")
            if d.get("resting_hr"):
                parts.append(f"resting HR {d['resting_hr']}")
            if d.get("stress_avg"):
                parts.append(f"stress {d['stress_avg']}")
            if d.get("body_battery_high") is not None:
                parts.append(f"body battery {d.get('body_battery_low', '?')}-{d['body_battery_high']}")
            print(", ".join(parts[:1]) + " " + ", ".join(parts[1:]))
        print()

    if hs["sleep"]:
        print("Sleep:")
        for s in hs["sleep"]:
            hrs = round(s.get("total_sleep_min", 0) / 60, 1) if s.get("total_sleep_min") else "?"
            score = s.get("sleep_score", "?")
            deep = s.get("deep_sleep_min", "?")
            rem = s.get("rem_sleep_min", "?")
            print(f"  {s['date']}: {hrs}h (score {score}, deep {deep}min, REM {rem}min)")
        print()

    if hs["readiness"]:
        print("Training Readiness:")
        for r in hs["readiness"]:
            print(f"  {r['date']}: score {r.get('score', '?')}, level {r.get('level', '?')}, recovery {r.get('recovery_time_hrs', '?')}h")
        print()

    if hs["hrv"]:
        print("HRV:")
        for h in hs["hrv"]:
            print(f"  {h['date']}: weekly avg {h.get('weekly_avg', '?')}, last night {h.get('last_night', '?')}, status {h.get('status', '?')}")
        print()

    # Training overview
    to = training_overview.fn(days=args.days)
    if to["activities"]:
        print(f"=== Training Overview (last {args.days} days) ===\n")

        if to["by_type"]:
            print("By type:")
            for t in to["by_type"]:
                km = f", {t['total_km']}km" if t.get("total_km") else ""
                print(f"  {t['type']}: {t['count']}x, {t['total_min']}min{km}, avg HR {t.get('mean_hr', '?')}")
            print()

        print("Recent activities:")
        for a in to["activities"][:10]:
            km = f" {a['distance_km']}km," if a.get("distance_km") else ""
            print(f"  {a['date']} {a['name']} ({a['type']}):{km} {a['duration_min']}min, HR {a.get('avg_hr', '?')}")
        print()

    ts = to.get("latest_training_status")
    if ts and (ts.get("vo2max") or ts.get("load_7d")):
        print("Training Status:")
        parts = []
        if ts.get("vo2max"):
            parts.append(f"VO2max {ts['vo2max']}")
        if ts.get("load_7d"):
            parts.append(f"7d load {ts['load_7d']}")
        if ts.get("load_28d"):
            parts.append(f"28d load {ts['load_28d']}")
        print(f"  {', '.join(parts)}")
        print()

    rp = to.get("latest_race_predictions")
    if rp and rp.get("five_k_sec"):
        print("Race Predictions:")
        for label, key in [("5K", "five_k_sec"), ("10K", "ten_k_sec"), ("Half Marathon", "half_marathon_sec"), ("Marathon", "marathon_sec")]:
            secs = rp.get(key)
            if secs:
                m, s = divmod(int(secs), 60)
                h, m = divmod(m, 60)
                t = f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"
                print(f"  {label}: {t}")
        print()


# ── garmin-coach-query ────────────────────────────────────────────────────────


def cmd_query():
    """Run a read-only SQL query and print results."""
    parser = argparse.ArgumentParser(
        prog="garmin-coach-query",
        description="Run a read-only SQL query against the Garmin database.",
    )
    parser.add_argument(
        "sql", nargs="?",
        help="SQL query to run (SELECT only)",
    )
    parser.add_argument(
        "--sql", dest="sql_flag",
        help="SQL query (alternative to positional arg)",
    )
    parser.add_argument(
        "--db", default=DEFAULT_DB,
        help=f"Path to SQLite database (default: {DEFAULT_DB})",
    )
    parser.add_argument(
        "--limit", type=int, default=100,
        help="Max rows to return (default: 100)",
    )
    args = parser.parse_args()

    sql = args.sql or args.sql_flag
    if not sql:
        print("Error: No SQL query provided. Usage: garmin-coach-query \"SELECT ...\"", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(args.db):
        print("Error: No Garmin database found. Run garmin-coach-sync first.", file=sys.stderr)
        sys.exit(1)

    os.environ["GARMIN_COACH_DB"] = args.db

    from .server import query

    result = query.fn(sql=sql, limit=args.limit)

    if "error" in result:
        print(f"Error: {result['error']}", file=sys.stderr)
        sys.exit(1)

    columns = result.get("columns", [])
    rows = result.get("rows", [])

    if not rows:
        print("(no results)")
        return

    # Calculate column widths
    widths = {c: len(str(c)) for c in columns}
    for row in rows:
        for c in columns:
            widths[c] = max(widths[c], len(str(row.get(c, ""))))

    # Print header
    header = " | ".join(str(c).ljust(widths[c]) for c in columns)
    print(header)
    print("-+-".join("-" * widths[c] for c in columns))

    # Print rows
    for row in rows:
        line = " | ".join(str(row.get(c, "")).ljust(widths[c]) for c in columns)
        print(line)

    if result.get("truncated"):
        print(f"\n(truncated at {args.limit} rows)")


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
