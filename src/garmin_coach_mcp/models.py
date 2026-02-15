"""SQLAlchemy models — 13 tables covering activities, health, training intelligence."""

from sqlalchemy import Column, Integer, Float, Text, String, create_engine
from sqlalchemy.orm import declarative_base, Session

Base = declarative_base()


# ── Core tables ──────────────────────────────────────────────────────────────


class Activity(Base):
    __tablename__ = "activities"

    id = Column(Text, primary_key=True)
    name = Column(Text)
    type = Column(Text)
    date = Column(Text)
    duration_min = Column(Float)
    distance_km = Column(Float)
    calories = Column(Integer)
    avg_hr = Column(Integer)
    max_hr = Column(Integer)
    avg_pace = Column(Text)
    elevation_m = Column(Float)
    steps = Column(Integer)
    training_effect = Column(Float)
    vo2max = Column(Float)
    raw_json = Column(Text)


class DailySummary(Base):
    __tablename__ = "daily_summary"

    date = Column(Text, primary_key=True)
    steps = Column(Integer)
    floors = Column(Integer)
    calories_total = Column(Integer)
    calories_active = Column(Integer)
    distance_km = Column(Float)
    active_minutes = Column(Integer)
    intensity_minutes = Column(Integer)
    resting_hr = Column(Integer)
    stress_avg = Column(Integer)
    body_battery_high = Column(Integer)
    body_battery_low = Column(Integer)
    raw_json = Column(Text)


class Sleep(Base):
    __tablename__ = "sleep"

    date = Column(Text, primary_key=True)
    total_sleep_min = Column(Integer)
    deep_sleep_min = Column(Integer)
    light_sleep_min = Column(Integer)
    rem_sleep_min = Column(Integer)
    awake_min = Column(Integer)
    sleep_score = Column(Integer)
    raw_json = Column(Text)


class HeartRate(Base):
    __tablename__ = "heart_rate"

    date = Column(Text, primary_key=True)
    resting_hr = Column(Integer)
    min_hr = Column(Integer)
    max_hr = Column(Integer)
    raw_json = Column(Text)


class BodyComposition(Base):
    __tablename__ = "body_composition"

    date = Column(Text, primary_key=True)
    weight_kg = Column(Float)
    bmi = Column(Float)
    body_fat_pct = Column(Float)
    muscle_mass_kg = Column(Float)
    raw_json = Column(Text)


# ── Training intelligence ────────────────────────────────────────────────────


class TrainingReadiness(Base):
    __tablename__ = "training_readiness"

    date = Column(Text, primary_key=True)
    score = Column(Integer)
    level = Column(Text)
    hrv_status = Column(Text)
    sleep_score = Column(Integer)
    recovery_time_hrs = Column(Integer)
    raw_json = Column(Text)


class HRV(Base):
    __tablename__ = "hrv"

    date = Column(Text, primary_key=True)
    weekly_avg = Column(Integer)
    last_night = Column(Integer)
    baseline_low = Column(Integer)
    baseline_high = Column(Integer)
    status = Column(Text)
    raw_json = Column(Text)


class TrainingStatus(Base):
    __tablename__ = "training_status"

    date = Column(Text, primary_key=True)
    status = Column(Text)
    load_7d = Column(Float)
    load_28d = Column(Float)
    vo2max = Column(Float)
    fitness_age = Column(Integer)
    raw_json = Column(Text)


class RacePrediction(Base):
    __tablename__ = "race_predictions"

    date = Column(Text, primary_key=True)
    five_k_sec = Column(Integer)
    ten_k_sec = Column(Integer)
    half_marathon_sec = Column(Integer)
    marathon_sec = Column(Integer)
    raw_json = Column(Text)


class PersonalRecord(Base):
    __tablename__ = "personal_records"

    id = Column(Text, primary_key=True)
    type = Column(Text)
    activity_type = Column(Text)
    value = Column(Float)
    value_display = Column(Text)
    date = Column(Text)
    activity_id = Column(Text)
    raw_json = Column(Text)


# ── Per-activity detail ──────────────────────────────────────────────────────


class ActivityHRZone(Base):
    __tablename__ = "activity_hr_zones"

    activity_id = Column(Text, primary_key=True)
    zone = Column(Integer, primary_key=True)
    zone_name = Column(Text)
    min_hr = Column(Integer)
    max_hr = Column(Integer)
    duration_sec = Column(Integer)
    raw_json = Column(Text)


class ActivitySplit(Base):
    __tablename__ = "activity_splits"

    activity_id = Column(Text, primary_key=True)
    split_num = Column(Integer, primary_key=True)
    distance_km = Column(Float)
    duration_sec = Column(Float)
    avg_hr = Column(Integer)
    max_hr = Column(Integer)
    avg_pace = Column(Text)
    elevation_gain_m = Column(Float)
    elevation_loss_m = Column(Float)
    calories = Column(Integer)
    raw_json = Column(Text)


# ── Fitness trends ───────────────────────────────────────────────────────────


class FitnessScore(Base):
    __tablename__ = "fitness_scores"

    date = Column(Text, primary_key=True)
    endurance_score = Column(Float)
    hill_score = Column(Float)
    raw_json = Column(Text)


# ── DB helpers ───────────────────────────────────────────────────────────────


def init_db(db_path: str) -> Session:
    """Create tables and return a session."""
    engine = create_engine(f"sqlite:///{db_path}", echo=False)
    Base.metadata.create_all(engine)
    from sqlalchemy.orm import sessionmaker
    return sessionmaker(bind=engine)()
