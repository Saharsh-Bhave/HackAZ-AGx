"""Candidate spray-window forecasting from hourly regional weather data."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DEFAULT_FORECAST_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "nws_forecast_hourly.json"
)


@dataclass(frozen=True)
class ForecastHour:
    start: datetime
    end: datetime
    temperature_f: float
    wind_mph: float
    precipitation_pct: float
    is_daytime: bool
    summary: str


@dataclass(frozen=True)
class SprayWindow:
    start: datetime
    end: datetime
    minimum_wind_mph: float
    maximum_wind_mph: float
    minimum_temperature_f: float
    maximum_temperature_f: float
    maximum_precipitation_pct: float
    confidence: str = "Moderate"

    @property
    def duration_hours(self) -> float:
        return (self.end - self.start).total_seconds() / 3600


def _parse_wind_speed(value: str) -> float:
    speeds = [float(number) for number in re.findall(r"\d+(?:\.\d+)?", value)]
    if not speeds:
        raise ValueError(f"Could not parse forecast wind speed: {value!r}")
    return max(speeds)


def load_hourly_forecast(
    path: Path = DEFAULT_FORECAST_PATH,
) -> list[ForecastHour]:
    with path.open(encoding="utf-8") as source:
        payload = json.load(source)

    hours = []
    for period in payload["properties"]["periods"]:
        precipitation = period.get("probabilityOfPrecipitation", {}).get("value")
        hours.append(
            ForecastHour(
                start=datetime.fromisoformat(period["startTime"]),
                end=datetime.fromisoformat(period["endTime"]),
                temperature_f=float(period["temperature"]),
                wind_mph=_parse_wind_speed(period["windSpeed"]),
                precipitation_pct=float(precipitation or 0),
                is_daytime=bool(period["isDaytime"]),
                summary=str(period.get("shortForecast", "")),
            )
        )
    return hours


def find_candidate_windows(
    hours: list[ForecastHour],
    as_of: datetime,
    duration_hours: float = 2,
    minimum_wind_mph: float = 3,
    maximum_wind_mph: float = 10,
    maximum_temperature_f: float = 90,
    maximum_precipitation_pct: float = 20,
) -> list[SprayWindow]:
    """Group contiguous qualifying daytime hours into advisory windows."""
    qualifying = [
        hour
        for hour in hours
        if hour.end > as_of
        and hour.is_daytime
        and minimum_wind_mph <= hour.wind_mph <= maximum_wind_mph
        and hour.temperature_f <= maximum_temperature_f
        and hour.precipitation_pct <= maximum_precipitation_pct
    ]

    groups: list[list[ForecastHour]] = []
    for hour in qualifying:
        if groups and groups[-1][-1].end == hour.start:
            groups[-1].append(hour)
        else:
            groups.append([hour])

    windows = []
    for group in groups:
        start = max(group[0].start, as_of)
        end = group[-1].end
        if (end - start).total_seconds() < duration_hours * 3600:
            continue
        windows.append(
            SprayWindow(
                start=start,
                end=end,
                minimum_wind_mph=min(hour.wind_mph for hour in group),
                maximum_wind_mph=max(hour.wind_mph for hour in group),
                minimum_temperature_f=min(
                    hour.temperature_f for hour in group
                ),
                maximum_temperature_f=max(
                    hour.temperature_f for hour in group
                ),
                maximum_precipitation_pct=max(
                    hour.precipitation_pct for hour in group
                ),
            )
        )
    return windows


def format_window(window: SprayWindow) -> str:
    return (
        f"{window.start:%a %b %d, %I:%M %p}–{window.end:%I:%M %p} "
        f"({window.duration_hours:.1f} h), wind "
        f"{window.minimum_wind_mph:.0f}–{window.maximum_wind_mph:.0f} mph, "
        f"temperature {window.minimum_temperature_f:.0f}–"
        f"{window.maximum_temperature_f:.0f}°F"
    )
