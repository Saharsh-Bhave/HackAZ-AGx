"""Tests for advisory spray-window forecasting."""

from datetime import datetime, timedelta, timezone

from driftguard.forecast import (
    ForecastHour,
    find_candidate_windows,
    load_hourly_forecast,
)


def hour(
    start: datetime,
    *,
    wind: float = 5,
    temperature: float = 70,
    precipitation: float = 0,
    daytime: bool = True,
) -> ForecastHour:
    return ForecastHour(
        start=start,
        end=start + timedelta(hours=1),
        temperature_f=temperature,
        wind_mph=wind,
        precipitation_pct=precipitation,
        is_daytime=daytime,
        summary="Test forecast",
    )


def test_contiguous_safe_hours_form_window() -> None:
    start = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
    hours = [hour(start + timedelta(hours=index)) for index in range(3)]

    windows = find_candidate_windows(hours, start, duration_hours=2)

    assert len(windows) == 1
    assert windows[0].start == start
    assert windows[0].end == start + timedelta(hours=3)
    assert windows[0].duration_hours == 3


def test_unsafe_hour_splits_and_removes_short_windows() -> None:
    start = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
    hours = [
        hour(start),
        hour(start + timedelta(hours=1), wind=12),
        hour(start + timedelta(hours=2)),
    ]

    assert find_candidate_windows(hours, start, duration_hours=2) == []


def test_night_rain_and_temperature_are_excluded() -> None:
    start = datetime(2026, 11, 15, 9, tzinfo=timezone.utc)
    hours = [
        hour(start, daytime=False),
        hour(start + timedelta(hours=1), precipitation=30),
        hour(start + timedelta(hours=2), temperature=95),
    ]

    assert find_candidate_windows(hours, start, duration_hours=1) == []


def test_supplied_forecast_loads_chronologically() -> None:
    forecast = load_hourly_forecast()

    assert len(forecast) > 100
    assert forecast[0].start < forecast[-1].start
    assert all(hour.wind_mph >= 0 for hour in forecast)
