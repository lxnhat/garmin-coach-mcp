"""FastMCP server — exposes Garmin coaching tools over MCP (stdio)."""

from __future__ import annotations

import json
import re
import os
from datetime import datetime, timedelta
from typing import Any

from fastmcp import FastMCP
from sqlalchemy import create_engine, text, inspect
from sqlalchemy.orm import sessionmaker, Session

from . import models

# ── Server setup ─────────────────────────────────────────────────────────────

mcp = FastMCP(
    "Garmin Coach",
    instructions=(
        "Personal fitness coaching MCP server backed by a local Garmin Connect "
        "database.  Use explore_schema to discover tables, query to run SQL, "
        "and health_summary / training_overview for pre-built coaching views."
    ),
)


def _db_path() -> str:
    return os.environ.get("GARMIN_COACH_DB", os.path.expanduser("~/.garminconnect/garmin_coach.db"))


def _get_session() -> Session:
    engine = create_engine(f"sqlite:///{_db_path()}", echo=False)
    models.Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


# ── MCP Tools ────────────────────────────────────────────────────────────────


@mcp.tool
def explore_schema() -> dict[str, Any]:
    """List all tables, their columns (name + type), and row counts.

    Use this to understand what data is available before writing queries.
    """
    session = _get_session()
    try:
        engine = session.get_bind()
        insp = inspect(engine)
        result: dict[str, Any] = {}
        for table in insp.get_table_names():
            cols = [
                {"name": c["name"], "type": str(c["type"])}
                for c in insp.get_columns(table)
            ]
            row_count = session.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()
            result[table] = {"columns": cols, "row_count": row_count}
        return result
    finally:
        session.close()


@mcp.tool
def query(sql: str, limit: int = 100) -> dict[str, Any]:
    """Run a read-only SQL query against the Garmin database.

    Only SELECT statements are allowed. Results are capped at *limit* rows
    (default 100, max 1000).  Returns column names and rows as dicts.
    """
    # Validate read-only
    normalized = sql.strip().upper()
    if not normalized.startswith("SELECT"):
        return {"error": "Only SELECT queries are allowed."}
    # Block dangerous patterns
    if re.search(r"\b(DROP|DELETE|UPDATE|INSERT|ALTER|CREATE|ATTACH)\b", normalized):
        return {"error": "Modification queries are not allowed."}

    limit = min(limit, 1000)
    session = _get_session()
    try:
        result = session.execute(text(sql))
        rows = [dict(row._mapping) for row in result.fetchmany(limit)]
        return {
            "columns": list(result.keys()),
            "rows": rows,
            "row_count": len(rows),
            "truncated": len(rows) == limit,
        }
    except Exception as e:
        return {"error": str(e)}
    finally:
        session.close()


@mcp.tool
def health_summary(days: int = 7) -> dict[str, Any]:
    """Pre-built health dashboard for the last N days.

    Returns daily steps, sleep scores, resting HR, stress, body battery,
    training readiness, and HRV trends — ready for coaching analysis.
    """
    session = _get_session()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        daily = _rows_to_dicts(session, text(
            "SELECT date, steps, calories_total, active_minutes, resting_hr, "
            "stress_avg, body_battery_high, body_battery_low "
            "FROM daily_summary WHERE date >= :cutoff ORDER BY date"
        ), {"cutoff": cutoff})

        sleep = _rows_to_dicts(session, text(
            "SELECT date, total_sleep_min, deep_sleep_min, rem_sleep_min, sleep_score "
            "FROM sleep WHERE date >= :cutoff ORDER BY date"
        ), {"cutoff": cutoff})

        readiness = _rows_to_dicts(session, text(
            "SELECT date, score, level, recovery_time_hrs "
            "FROM training_readiness WHERE date >= :cutoff ORDER BY date"
        ), {"cutoff": cutoff})

        hrv = _rows_to_dicts(session, text(
            "SELECT date, weekly_avg, last_night, status "
            "FROM hrv WHERE date >= :cutoff ORDER BY date"
        ), {"cutoff": cutoff})

        return {
            "period": f"last {days} days (since {cutoff})",
            "daily": daily,
            "sleep": sleep,
            "readiness": readiness,
            "hrv": hrv,
        }
    finally:
        session.close()


@mcp.tool
def training_overview(days: int = 30) -> dict[str, Any]:
    """Activity volume, type distribution, and weekly trends.

    Covers the last N days of activities with total distance, duration,
    grouped by activity type, and training load/status.
    """
    session = _get_session()
    try:
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

        activities = _rows_to_dicts(session, text(
            "SELECT date, name, type, duration_min, distance_km, avg_hr, max_hr, "
            "training_effect, vo2max, elevation_m "
            "FROM activities WHERE date >= :cutoff ORDER BY date DESC"
        ), {"cutoff": cutoff})

        type_summary = _rows_to_dicts(session, text(
            "SELECT type, COUNT(*) as count, "
            "ROUND(SUM(duration_min), 1) as total_min, "
            "ROUND(SUM(distance_km), 2) as total_km, "
            "ROUND(AVG(avg_hr), 0) as mean_hr "
            "FROM activities WHERE date >= :cutoff "
            "GROUP BY type ORDER BY count DESC"
        ), {"cutoff": cutoff})

        training_status = _rows_to_dicts(session, text(
            "SELECT date, status, load_7d, load_28d, vo2max, fitness_age "
            "FROM training_status WHERE date >= :cutoff ORDER BY date DESC LIMIT 1"
        ), {"cutoff": cutoff})

        race_preds = _rows_to_dicts(session, text(
            "SELECT * FROM race_predictions ORDER BY date DESC LIMIT 1"
        ), {})

        return {
            "period": f"last {days} days (since {cutoff})",
            "activities": activities,
            "by_type": type_summary,
            "latest_training_status": training_status[0] if training_status else None,
            "latest_race_predictions": race_preds[0] if race_preds else None,
        }
    finally:
        session.close()


@mcp.tool
def sync_status() -> dict[str, Any]:
    """Check when data was last synced and how much data is stored."""
    session = _get_session()
    try:
        tables = {}
        for table_name in [
            "activities", "daily_summary", "sleep", "heart_rate",
            "body_composition", "training_readiness", "hrv",
            "training_status", "race_predictions", "personal_records",
            "activity_hr_zones", "activity_splits", "fitness_scores",
        ]:
            try:
                row_count = session.execute(
                    text(f'SELECT COUNT(*) FROM "{table_name}"')
                ).scalar()
                latest = session.execute(
                    text(f'SELECT MAX(date) FROM "{table_name}"')
                ).scalar()
            except Exception:
                row_count = 0
                latest = None
            tables[table_name] = {"rows": row_count, "latest_date": latest}

        return {
            "db_path": _db_path(),
            "tables": tables,
        }
    finally:
        session.close()


# ── helpers ──────────────────────────────────────────────────────────────────


def _rows_to_dicts(session: Session, stmt: Any, params: dict) -> list[dict]:
    result = session.execute(stmt, params)
    return [dict(row._mapping) for row in result.fetchall()]
