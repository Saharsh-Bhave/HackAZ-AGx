"""SQLite audit-log persistence for spray assessments."""

from __future__ import annotations

import csv
import io
import json
import sqlite3
from collections.abc import Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .models import ApplicationSettings, Assessment, SensorReading, WeatherReading

DEFAULT_DB_PATH = Path("data/driftguard.db")


def initialize_database(db_path: Path = DEFAULT_DB_PATH) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS assessments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recorded_at TEXT NOT NULL,
                observed_at TEXT,
                lower_temp_f REAL NOT NULL,
                upper_temp_f REAL NOT NULL,
                lower_wind_mph REAL NOT NULL,
                upper_wind_mph REAL NOT NULL,
                lower_direction_deg REAL NOT NULL,
                upper_direction_deg REAL NOT NULL,
                product_name TEXT NOT NULL,
                volatility TEXT NOT NULL,
                droplet_size TEXT NOT NULL,
                status TEXT NOT NULL,
                inversion_delta_f REAL NOT NULL,
                wind_speed_delta_mph REAL NOT NULL,
                wind_direction_delta_deg REAL NOT NULL,
                alert_codes TEXT NOT NULL,
                reasons TEXT NOT NULL
            )
            """
        )
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(assessments)")
        }
        if "sensor_profile" not in columns:
            connection.execute(
                "ALTER TABLE assessments ADD COLUMN sensor_profile TEXT"
            )
        if "observed_at" not in columns:
            connection.execute(
                "ALTER TABLE assessments ADD COLUMN observed_at TEXT"
            )


def save_assessment(
    reading: WeatherReading,
    application: ApplicationSettings,
    assessment: Assessment,
    db_path: Path = DEFAULT_DB_PATH,
    sensor_readings: Sequence[SensorReading] | None = None,
    observed_at: str | None = None,
) -> str:
    initialize_database(db_path)
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO assessments (
                recorded_at, observed_at, lower_temp_f, upper_temp_f, lower_wind_mph,
                upper_wind_mph, lower_direction_deg, upper_direction_deg,
                product_name, volatility, droplet_size, status,
                inversion_delta_f, wind_speed_delta_mph,
                wind_direction_delta_deg, alert_codes, reasons, sensor_profile
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recorded_at,
                observed_at,
                reading.lower_temp_f,
                reading.upper_temp_f,
                reading.lower_wind_mph,
                reading.upper_wind_mph,
                reading.lower_direction_deg,
                reading.upper_direction_deg,
                application.product_name,
                application.volatility.value,
                application.droplet_size.value,
                assessment.status.name,
                assessment.inversion_delta_f,
                assessment.wind_speed_delta_mph,
                assessment.wind_direction_delta_deg,
                json.dumps([alert.code for alert in assessment.alerts]),
                json.dumps([alert.explanation for alert in assessment.alerts]),
                json.dumps(
                    [
                        {
                            "height_ft": sensor.height_ft,
                            "temperature_f": sensor.temperature_f,
                            "wind_speed_mph": sensor.wind_speed_mph,
                            "wind_direction_deg": sensor.wind_direction_deg,
                        }
                        for sensor in (sensor_readings or ())
                    ]
                ),
            ),
        )
    return recorded_at


def get_assessments(
    status: str | None = None,
    limit: int = 200,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    query = "SELECT * FROM assessments"
    parameters: list[Any] = []
    if status and status != "All":
        query += " WHERE status = ?"
        parameters.append(status)
    query += " ORDER BY recorded_at DESC, id DESC LIMIT ?"
    parameters.append(limit)

    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]


def assessments_to_csv(records: list[dict[str, Any]]) -> str:
    if not records:
        return ""
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=records[0].keys())
    writer.writeheader()
    writer.writerows(records)
    return output.getvalue()


def create_notification(
    title: str,
    message: str,
    level: str,
    event_type: str,
    db_path: Path = DEFAULT_DB_PATH,
) -> str:
    """Persist an in-app notification and return its UTC timestamp."""
    if level not in {"success", "warning", "error", "info"}:
        raise ValueError(f"Unsupported notification level: {level}")
    initialize_database(db_path)
    created_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO notifications (
                created_at, level, event_type, title, message
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (created_at, level, event_type, title, message),
        )
    return created_at


def get_notifications(
    limit: int = 100,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[dict[str, Any]]:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT * FROM notifications
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def mark_all_notifications_read(db_path: Path = DEFAULT_DB_PATH) -> None:
    initialize_database(db_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE notifications SET is_read = 1")
