"""Tests for timestamped assessment persistence."""

from pathlib import Path

from driftguard.models import ApplicationSettings, WeatherReading
from driftguard.risk import assess_spray_risk
from driftguard.storage import get_assessments, save_assessment


def test_assessment_preserves_sensor_observation_time(tmp_path: Path) -> None:
    database = tmp_path / "assessments.db"
    observed_at = "2026-11-11T00:00:00-08:00"
    reading = WeatherReading(46.4, 51.4, 1.4, 3.5, 100, 122)

    save_assessment(
        reading,
        ApplicationSettings(),
        assess_spray_risk(reading),
        database,
        observed_at=observed_at,
    )

    record = get_assessments(db_path=database)[0]
    assert record["observed_at"] == observed_at
    assert record["status"] == "STOP"
