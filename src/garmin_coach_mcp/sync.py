"""Sync engine — fetch data from Garmin Connect and upsert into SQLite.

Covers 13 data categories.  Idempotent (upserts by date/id).
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from garminconnect import Garmin
from sqlalchemy.orm import Session

from .models import (
    Activity, ActivityHRZone, ActivitySplit,
    BodyComposition, DailySummary, FitnessScore,
    HRV, HeartRate, PersonalRecord,
    RacePrediction, Sleep, TrainingReadiness, TrainingStatus,
)


def sync_all(
    client: Garmin,
    session: Session,
    days: int = 30,
) -> dict[str, Any]:
    """Run a full sync for *days* days back.  Returns summary dict."""
    end = datetime.now()
    start = end - timedelta(days=days)

    results: dict[str, int] = {}
    warnings: list[str] = []

    # ── core (date-ranged) ───────────────────────────────────────────────
    act_ids: list[str] = []
    results["activities"], act_ids, err = _sync_activities(client, session, start, end)
    if err:
        warnings.append(f"activities: {err}")

    for name, fn in [
        ("daily_summary", _sync_daily_summaries),
        ("sleep", _sync_sleep),
        ("heart_rate", _sync_heart_rate),
        ("body_composition", _sync_body_composition),
        ("training_readiness", _sync_training_readiness),
        ("hrv", _sync_hrv),
        ("training_status", _sync_training_status),
        ("fitness_scores", _sync_fitness_scores),
    ]:
        count, err = fn(client, session, start, end)
        results[name] = count
        if err:
            warnings.append(f"{name}: {err}")

    # ── non-date-ranged ──────────────────────────────────────────────────
    for name, fn in [
        ("race_predictions", _sync_race_predictions),
        ("personal_records", _sync_personal_records),
    ]:
        count, err = fn(client, session)
        results[name] = count
        if err:
            warnings.append(f"{name}: {err}")

    # ── per-activity detail ──────────────────────────────────────────────
    if act_ids:
        for name, fn in [
            ("activity_hr_zones", _sync_activity_hr_zones),
            ("activity_splits", _sync_activity_splits),
        ]:
            count, err = fn(client, session, act_ids)
            results[name] = count
            if err:
                warnings.append(f"{name}: {err}")

    out: dict[str, Any] = {"status": "ok", "synced": results, "days": days}
    if warnings:
        out["warnings"] = warnings
    return out


# ═════════════════════════════════════════════════════════════════════════════
#  Internal helpers
# ═════════════════════════════════════════════════════════════════════════════


def _g(data: Any, *keys: str, default: Any = None) -> Any:
    """Safely navigate nested dicts."""
    for k in keys:
        if isinstance(data, dict):
            data = data.get(k, default)
        else:
            return default
    return data


def _date_range(start: datetime, end: datetime):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _upsert(session: Session, model: type, pk_filter: dict, values: dict) -> None:
    """Insert or update a row."""
    obj = session.get(model, pk_filter) if len(pk_filter) == 1 else session.query(model).filter_by(**pk_filter).first()
    if obj:
        for k, v in values.items():
            setattr(obj, k, v)
    else:
        session.add(model(**pk_filter, **values))


# ── Core sync ────────────────────────────────────────────────────────────────


def _sync_activities(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, list[str], str | None]:
    count = 0
    ids: list[str] = []
    try:
        activities = client.get_activities_by_date(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        )
        for a in activities:
            aid = str(a.get("activityId", ""))
            dur = a.get("duration", 0) or 0
            dist = a.get("distance", 0) or 0
            vals = dict(
                name=a.get("activityName", ""),
                type=_g(a, "activityType", "typeKey", default=""),
                date=(a.get("startTimeLocal") or "")[:10],
                duration_min=round(dur / 60, 1),
                distance_km=round(dist / 1000, 2) if dist else None,
                calories=a.get("calories"),
                avg_hr=a.get("averageHR"),
                max_hr=a.get("maxHR"),
                avg_pace=a.get("averagePace"),
                elevation_m=a.get("elevationGain"),
                steps=a.get("steps"),
                training_effect=a.get("aerobicTrainingEffect"),
                vo2max=a.get("vO2MaxValue"),
                raw_json=json.dumps(a),
            )
            _upsert(session, Activity, {"id": aid}, vals)
            ids.append(aid)
            count += 1
        session.commit()
    except Exception as e:
        session.rollback()
        return count, ids, str(e)
    return count, ids, None


def _sync_daily_summaries(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                stats = client.get_stats(ds)
                if not stats:
                    continue
                vals = dict(
                    steps=_g(stats, "totalSteps", default=0),
                    floors=_g(stats, "floorsAscended", default=0),
                    calories_total=_g(stats, "totalKilocalories"),
                    calories_active=_g(stats, "activeKilocalories"),
                    distance_km=round((_g(stats, "totalDistanceMeters", default=0) or 0) / 1000, 2),
                    active_minutes=(_g(stats, "activeSeconds", default=0) or 0) // 60,
                    intensity_minutes=_g(stats, "moderateIntensityMinutes", default=0),
                    resting_hr=_g(stats, "restingHeartRate"),
                    stress_avg=_g(stats, "averageStressLevel"),
                    body_battery_high=_g(stats, "bodyBatteryHighestValue"),
                    body_battery_low=_g(stats, "bodyBatteryLowestValue"),
                    raw_json=json.dumps(stats),
                )
                _upsert(session, DailySummary, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_sleep(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                sleep = client.get_sleep_data(ds)
                dto = _g(sleep, "dailySleepDTO")
                if not dto:
                    continue
                vals = dict(
                    total_sleep_min=(_g(dto, "sleepTimeSeconds", default=0) or 0) // 60,
                    deep_sleep_min=(_g(dto, "deepSleepSeconds", default=0) or 0) // 60,
                    light_sleep_min=(_g(dto, "lightSleepSeconds", default=0) or 0) // 60,
                    rem_sleep_min=(_g(dto, "remSleepSeconds", default=0) or 0) // 60,
                    awake_min=(_g(dto, "awakeSleepSeconds", default=0) or 0) // 60,
                    sleep_score=_g(dto, "sleepScores", "overall", "value"),
                    raw_json=json.dumps(sleep),
                )
                _upsert(session, Sleep, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_heart_rate(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                hr = client.get_heart_rates(ds)
                if not hr:
                    continue
                vals = dict(
                    resting_hr=_g(hr, "restingHeartRate"),
                    min_hr=_g(hr, "minHeartRate"),
                    max_hr=_g(hr, "maxHeartRate"),
                    raw_json=json.dumps(hr),
                )
                _upsert(session, HeartRate, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_body_composition(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        data = client.get_body_composition(
            start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        )
        for entry in _g(data, "dateWeightList") or []:
            ds = _g(entry, "calendarDate", default="")
            if not ds:
                continue
            wg = _g(entry, "weight", default=0) or 0
            mm = _g(entry, "muscleMass", default=0) or 0
            vals = dict(
                weight_kg=round(wg / 1000, 1) if wg else None,
                bmi=_g(entry, "bmi"),
                body_fat_pct=_g(entry, "bodyFat"),
                muscle_mass_kg=round(mm / 1000, 1) if mm else None,
                raw_json=json.dumps(entry),
            )
            _upsert(session, BodyComposition, {"date": ds}, vals)
            count += 1
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


# ── Training intelligence ────────────────────────────────────────────────────


def _sync_training_readiness(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                d = client.get_training_readiness(ds)
                if not d:
                    continue
                vals = dict(
                    score=_g(d, "score") or _g(d, "trainingReadinessScore"),
                    level=_g(d, "level") or _g(d, "trainingReadinessLevel"),
                    hrv_status=_g(d, "hrvStatus"),
                    sleep_score=_g(d, "sleepScore") or _g(d, "sleepQuality"),
                    recovery_time_hrs=_g(d, "recoveryTimeInHours") or _g(d, "recoveryTime"),
                    raw_json=json.dumps(d),
                )
                _upsert(session, TrainingReadiness, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_hrv(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                d = client.get_hrv_data(ds)
                if not d:
                    continue
                s = _g(d, "hrvSummary") or d
                vals = dict(
                    weekly_avg=_g(s, "weeklyAvg"),
                    last_night=_g(s, "lastNight") or _g(s, "lastNightAvg"),
                    baseline_low=_g(s, "baselineLow") or _g(s, "baseline", "lowUpper"),
                    baseline_high=_g(s, "baselineHigh") or _g(s, "baseline", "highUpper"),
                    status=_g(s, "status") or _g(s, "hrvStatus"),
                    raw_json=json.dumps(d),
                )
                _upsert(session, HRV, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_training_status(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        for cur in _date_range(start, end):
            ds = cur.strftime("%Y-%m-%d")
            try:
                d = client.get_training_status(ds)
                if not d:
                    continue
                # VO2max is nested under mostRecentVO2Max.generic
                vo2 = _g(d, "mostRecentVO2Max", "generic") or {}
                # Training load is nested under mostRecentTrainingLoadBalance
                load_map = _g(d, "mostRecentTrainingLoadBalance", "metricsTrainingLoadBalanceDTOMap") or {}
                load_dto = next(iter(load_map.values()), {}) if load_map else {}
                vals = dict(
                    status=_g(d, "trainingStatusPhrase") or _g(d, "trainingStatus"),
                    load_7d=_g(load_dto, "weeklyTrainingLoad") or _g(load_dto, "monthlyLoadAerobicLow"),
                    load_28d=_g(load_dto, "monthlyLoadAerobicHigh"),
                    vo2max=_g(vo2, "vo2MaxPreciseValue") or _g(vo2, "vo2MaxValue"),
                    fitness_age=_g(vo2, "fitnessAge") or _g(d, "fitnessAge"),
                    raw_json=json.dumps(d),
                )
                _upsert(session, TrainingStatus, {"date": ds}, vals)
                count += 1
            except Exception:
                pass
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _sync_fitness_scores(
    client: Garmin, session: Session, start: datetime, end: datetime
) -> tuple[int, str | None]:
    count = 0
    try:
        s_str, e_str = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
        endurance: dict[str, float] = {}
        hill: dict[str, float] = {}

        try:
            raw = client.get_endurance_score(s_str, e_str)
            if raw:
                for e in (raw if isinstance(raw, list) else _g(raw, "enduranceScoreDTOList") or [raw]):
                    d = _g(e, "calendarDate") or _g(e, "date") or ""
                    if d:
                        endurance[d] = _g(e, "overallScore") or _g(e, "enduranceScore")
        except Exception:
            pass

        try:
            raw = client.get_hill_score(s_str, e_str)
            if raw:
                for e in (raw if isinstance(raw, list) else _g(raw, "hillScoreDTOList") or [raw]):
                    d = _g(e, "calendarDate") or _g(e, "date") or ""
                    if d:
                        hill[d] = _g(e, "overallScore") or _g(e, "hillScore")
        except Exception:
            pass

        for ds in set(endurance) | set(hill):
            vals = dict(
                endurance_score=endurance.get(ds),
                hill_score=hill.get(ds),
                raw_json=json.dumps({"endurance": endurance.get(ds), "hill": hill.get(ds)}),
            )
            _upsert(session, FitnessScore, {"date": ds}, vals)
            count += 1
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


# ── Non-date-ranged ──────────────────────────────────────────────────────────


def _sync_race_predictions(
    client: Garmin, session: Session
) -> tuple[int, str | None]:
    count = 0
    try:
        d = client.get_race_predictions()
        if d:
            preds = d if isinstance(d, dict) else {}
            ds = _g(preds, "calendarDate") or datetime.now().strftime("%Y-%m-%d")
            vals = dict(
                five_k_sec=_to_sec(_g(preds, "time5K") or _g(preds, "5k", "time")),
                ten_k_sec=_to_sec(_g(preds, "time10K") or _g(preds, "10k", "time")),
                half_marathon_sec=_to_sec(_g(preds, "timeHalfMarathon") or _g(preds, "half", "time")),
                marathon_sec=_to_sec(_g(preds, "timeMarathon") or _g(preds, "marathon", "time")),
                raw_json=json.dumps(d),
            )
            _upsert(session, RacePrediction, {"date": ds}, vals)
            count = 1
        session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


def _to_sec(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and ":" in value:
        parts = value.split(":")
        try:
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            pass
    return None


def _sync_personal_records(
    client: Garmin, session: Session
) -> tuple[int, str | None]:
    count = 0
    try:
        d = client.get_personal_record()
        if d:
            records = d if isinstance(d, list) else _g(d, "personalRecords") or []
            for rec in records:
                rid = str(_g(rec, "id") or "")
                if not rid:
                    continue
                type_id = _g(rec, "typeId")
                atype = _g(rec, "activityType") or ""
                # Extract date from formatted GMT string
                ds = _g(rec, "actStartDateTimeInGMTFormatted") or ""
                if ds and "T" in ds:
                    ds = ds[:10]
                vals = dict(
                    type=str(type_id) if type_id is not None else "",
                    activity_type=atype,
                    value=_g(rec, "value"),
                    value_display=_g(rec, "activityName") or "",
                    date=ds,
                    activity_id=str(_g(rec, "activityId") or ""),
                    raw_json=json.dumps(rec),
                )
                _upsert(session, PersonalRecord, {"id": rid}, vals)
                count += 1
            session.commit()
    except Exception as e:
        session.rollback()
        return count, str(e)
    return count, None


# ── Per-activity detail ──────────────────────────────────────────────────────


def _sync_activity_hr_zones(
    client: Garmin, session: Session, activity_ids: list[str]
) -> tuple[int, str | None]:
    """Fetch HR zone breakdowns per activity.

    Note: the /hrTimeInZones endpoint returns 403 for many accounts.
    This function tries it but gracefully returns 0 if unavailable.
    """
    count = 0
    errors: list[str] = []
    for aid in activity_ids:
        try:
            d = client.get_activity_hr_in_timezones(aid)
            if not d:
                continue
            zones = d if isinstance(d, list) else _g(d, "hrTimeInZones") or []
            # Garmin only gives zoneLowBoundary — compute max from next zone
            for i, z in enumerate(zones):
                zn = _g(z, "zoneNumber", default=i + 1)
                min_hr = _g(z, "zoneLowBoundary") or _g(z, "startBpm")
                # Max HR = next zone's low boundary - 1 (last zone has no upper)
                if i + 1 < len(zones):
                    max_hr = (_g(zones[i + 1], "zoneLowBoundary") or 0) - 1
                else:
                    max_hr = None
                vals = dict(
                    zone_name=f"Zone {zn}",
                    min_hr=min_hr,
                    max_hr=max_hr if max_hr and max_hr > 0 else None,
                    duration_sec=_g(z, "secsInZone") or _g(z, "duration"),
                    raw_json=json.dumps(z),
                )
                _upsert(session, ActivityHRZone, {"activity_id": str(aid), "zone": zn}, vals)
                count += 1
            session.commit()
        except Exception:
            session.rollback()
            # 403 is common — don't accumulate per-activity errors
            pass
    return count, None


def _sync_activity_splits(
    client: Garmin, session: Session, activity_ids: list[str]
) -> tuple[int, str | None]:
    """Fetch splits from get_activity().splitSummaries (the /splits endpoint is 403)."""
    count = 0
    errors: list[str] = []
    for aid in activity_ids:
        try:
            d = client.get_activity(aid)
            if not d:
                continue
            splits = _g(d, "splitSummaries") or []
            for i, sp in enumerate(splits):
                dist_m = _g(sp, "distance", default=0) or 0
                dur_s = _g(sp, "duration", default=0) or 0
                sn = i + 1
                # Convert averageSpeed (m/s) to pace (min/km)
                avg_speed = _g(sp, "averageSpeed")
                pace_str = None
                if avg_speed and avg_speed > 0:
                    pace_s_per_km = 1000 / avg_speed
                    pm, ps = divmod(int(pace_s_per_km), 60)
                    pace_str = f"{pm}:{ps:02d}"
                vals = dict(
                    distance_km=round(dist_m / 1000, 3) if dist_m else None,
                    duration_sec=round(dur_s, 1),
                    avg_hr=_g(sp, "averageHR"),
                    max_hr=_g(sp, "maxHR"),
                    avg_pace=pace_str,
                    elevation_gain_m=_g(sp, "elevationGain"),
                    elevation_loss_m=_g(sp, "elevationLoss"),
                    calories=_g(sp, "calories"),
                    raw_json=json.dumps(sp),
                )
                _upsert(session, ActivitySplit, {"activity_id": str(aid), "split_num": sn}, vals)
                count += 1
            session.commit()
        except Exception as e:
            session.rollback()
            errors.append(f"splits({aid}): {e}")
    return count, "; ".join(errors) if errors else None
