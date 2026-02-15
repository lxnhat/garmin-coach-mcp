# garmin-coach-mcp

MCP server for fitness coaching backed by a local Garmin Connect SQLite database.

## Quick start

```bash
pip install -e .

# 1. Authenticate (one time — supports MFA)
garmin-coach-auth --email you@example.com

# 2. Sync data
garmin-coach-sync --days 90

# 3. Start MCP server
garmin-coach-mcp
```

## Architecture

```
Garmin Connect API  -->  sync engine  -->  SQLite (13 tables)
                                                |
                                          FastMCP server (stdio)
                                                |
                                          Any MCP client
```

## MCP tools

| Tool | Description |
|------|-------------|
| `explore_schema` | List tables, columns, row counts |
| `query` | Read-only SQL against the database |
| `health_summary` | Pre-built health dashboard (steps, sleep, HR, stress, readiness) |
| `training_overview` | Activity volume, type distribution, training load |
| `sync_status` | When data was last synced, table row counts |

## Database

13 tables covering:

- **Core**: activities, daily_summary, sleep, heart_rate, body_composition
- **Training intelligence**: training_readiness, hrv, training_status, race_predictions, personal_records
- **Per-activity detail**: activity_hr_zones, activity_splits
- **Fitness trends**: fitness_scores

All tables include `raw_json` for future-proofing.

## Environment variables

- `GARMIN_EMAIL` — Garmin Connect email
- `GARMIN_PASSWORD` — Garmin Connect password
- `GARMIN_COACH_DB` — Path to SQLite database (default: `~/.garminconnect/garmin_coach.db`)
