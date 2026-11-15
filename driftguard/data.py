"""Load simulated multi-height weather scenarios."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import SensorReading, WeatherReading

DEFAULT_SCENARIOS_PATH = Path(__file__).resolve().parents[1] / "data" / "scenarios.json"


@dataclass(frozen=True)
class Scenario:
    id: str
    name: str
    description: str
    timestamp: str
    reading: WeatherReading
    sensor_readings: tuple[SensorReading, ...]
    intended_hazards: tuple[str, ...]


def _has_weather_values(sensor: dict[str, Any]) -> bool:
    required = (
        "height_ft",
        "temperature_f",
        "wind_speed_mph",
        "wind_direction_deg",
    )
    return sensor.get("quality") != "missing" and all(
        sensor.get(field) is not None for field in required
    )


def scenario_from_dict(raw: dict[str, Any]) -> Scenario:
    """Convert one scenario, using the lowest and highest valid sensor heights."""
    sensors = sorted(
        (sensor for sensor in raw["readings"] if _has_weather_values(sensor)),
        key=lambda sensor: float(sensor["height_ft"]),
    )
    if len(sensors) < 2:
        raise ValueError(
            f"Scenario {raw.get('id', '<unknown>')} needs two valid sensor heights"
        )

    lower, upper = sensors[0], sensors[-1]
    sensor_readings = tuple(
        SensorReading(
            height_ft=float(sensor["height_ft"]),
            temperature_f=float(sensor["temperature_f"]),
            wind_speed_mph=float(sensor["wind_speed_mph"]),
            wind_direction_deg=float(sensor["wind_direction_deg"]),
        )
        for sensor in sensors
    )
    return Scenario(
        id=str(raw["id"]),
        name=str(raw["name"]),
        description=str(raw.get("description", "")),
        timestamp=str(raw["timestamp"]),
        reading=WeatherReading(
            lower_temp_f=float(lower["temperature_f"]),
            upper_temp_f=float(upper["temperature_f"]),
            lower_wind_mph=float(lower["wind_speed_mph"]),
            upper_wind_mph=float(upper["wind_speed_mph"]),
            lower_direction_deg=float(lower["wind_direction_deg"]),
            upper_direction_deg=float(upper["wind_direction_deg"]),
            lower_height_ft=float(lower["height_ft"]),
            upper_height_ft=float(upper["height_ft"]),
        ),
        sensor_readings=sensor_readings,
        intended_hazards=tuple(raw.get("intended_hazards", ())),
    )


def load_scenarios(path: Path = DEFAULT_SCENARIOS_PATH) -> list[Scenario]:
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)
    return [scenario_from_dict(raw) for raw in payload["scenarios"]]
