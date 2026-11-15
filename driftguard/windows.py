"""Predict suitable spray windows and the next one after a GO."""

from __future__ import annotations

import csv
import json
import re
from collections import defaultdict
from functools import lru_cache
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Any

from .models import RiskThresholds, SensorReading, Status, WeatherReading
from .risk import assess_multi_height_risk, assess_spray_risk

DEFAULT_FORECAST_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "nws_forecast_hourly.json"
)
DEFAULT_TOWER_PATH = Path(__file__).resolve().parents[1] / "data" / "tower_readings.csv"
DEFAULT_PRODUCTS_PATH = Path(__file__).resolve().parents[1] / "data" / "products.json"
DEFAULT_SITE_PATH = Path(__file__).resolve().parents[1] / "data" / "site.json"
DEFAULT_APPLICATIONS_PATH = (
    Path(__file__).resolve().parents[1] / "data" / "applications.csv"
)

_WIND_SPEED = re.compile(r"\d+(?:\.\d+)?")


@dataclass(frozen=True)
class SprayLimits:
    """Label limits, plus the schedule settings this tool adds."""

    min_wind_mph: float = 3.0
    max_wind_mph: float = 10.0
    max_temp_f: float = 90.0
    max_precip_probability: float = 30.0
    spray_start: time = time(4, 0)
    spray_end: time = time(22, 0)
    minimum_window: timedelta = timedelta(hours=2)


@dataclass(frozen=True)
class HourAssessment:
    start: datetime
    end: datetime
    suitable: bool
    inversion_checked: bool
    wind_mph: float | None
    temperature_f: float | None
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class SprayWindow:
    start: datetime
    end: datetime
    inversion_checked: bool
    likelihood: str = "Possible"
    opens_because: str = ""
    closes_because: str = ""

    @property
    def duration(self) -> timedelta:
        return self.end - self.start


@dataclass(frozen=True)
class NextWindowAlert:
    """On-screen alert and the shorter ntfy push sent with a Go."""

    go_given_at: datetime
    current_window: SprayWindow | None
    next_window: SprayWindow | None
    message: str
    push: str = ""


@dataclass(frozen=True)
class SprayJob:
    application_id: str
    status: str
    block_id: str
    product_id: str
    earliest_start: datetime | None
    latest_end: datetime | None
    duration: timedelta
    notes: str


def parse_wind_mph(text: str) -> float | None:
    """Parse an NWS wind string. A range uses the higher speed."""
    speeds = [float(match) for match in _WIND_SPEED.findall(text)]
    if not speeds:
        return None
    return max(speeds)


def format_clock(moment: datetime | time) -> str:
    """Clock style shared by the screen and the push: 9 AM, 2:30 PM."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    if moment.minute:
        return f"{hour}:{moment.minute:02d} {suffix}"
    return f"{hour} {suffix}"


def format_window_span(window: SprayWindow) -> str:
    return f"{window.start:%a} {format_clock(window.start)}–{format_clock(window.end)}"


def format_spray_window(window: SprayWindow) -> str:
    return format_window_span(window)


def confidence_marker(window: SprayWindow) -> str:
    """One marker. Forecast hours leave inversion unseen."""
    if window.inversion_checked:
        return "Tower"
    return "Inversion unseen"


def window_why(window: SprayWindow) -> str:
    return ". ".join(
        part for part in (window.opens_because, window.closes_because) if part
    )


def latest_start(
    window: SprayWindow,
    duration: timedelta,
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> datetime | None:
    """Last moment a job of this length can start and still finish in the window."""
    start = window.start if earliest is None else max(window.start, earliest)
    end = window.end if latest is None else min(window.end, latest)
    if end - start < duration:
        return None
    return end - duration


def planned_why(
    window: SprayWindow, earliest: datetime, latest: datetime
) -> str:
    """Weather edge when it binds, otherwise the plan's own end."""
    parts: list[str] = []
    if window.start >= earliest and window.opens_because:
        parts.append(window.opens_because)
    if latest < window.end:
        parts.append(f"Plan ends at {format_clock(latest)}")
    elif window.closes_because:
        parts.append(window.closes_because)
    return ". ".join(parts)


def push_text(
    window: SprayWindow,
    duration: timedelta,
    lead: str,
    earliest: datetime | None = None,
    latest: datetime | None = None,
) -> str:
    """Short ntfy line. The on-screen alert carries the reason."""
    usable_start = window.start if earliest is None else max(window.start, earliest)
    usable_end = window.end if latest is None else min(window.end, latest)
    start_by = latest_start(window, duration, earliest, latest)
    if start_by is None:
        return f"{lead}. No window."
    span = f"{usable_start:%a} {format_clock(usable_start)}–{format_clock(usable_end)}"
    return (
        f"{lead} {span}. Start by {format_clock(start_by)}. "
        f"{confidence_marker(window)}."
    )


def limits_for_product(
    product: Mapping[str, Any] | None = None,
    site: Mapping[str, Any] | None = None,
) -> SprayLimits:
    """Label wind, temperature, and rain come from the product.

    Spray hours and the minimum window are this tool's settings. `site` is
    accepted so callers can pass the orchard record without using its sunrise.
    """
    del site
    if not product:
        return SprayLimits()
    return SprayLimits(
        min_wind_mph=float(product.get("label_min_wind_mph", 3)),
        max_wind_mph=float(product.get("label_max_wind_mph", 10)),
        max_temp_f=float(product.get("label_max_temp_f", 90)),
    )


@lru_cache(maxsize=4)
def load_products(path: Path = DEFAULT_PRODUCTS_PATH) -> tuple[dict[str, Any], ...]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return tuple(payload["products"])


@lru_cache(maxsize=4)
def load_site(path: Path = DEFAULT_SITE_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=4)
def load_forecast_periods(path: Path = DEFAULT_FORECAST_PATH) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(payload["properties"]["periods"])


@lru_cache(maxsize=4)
def load_tower_index(
    path: Path = DEFAULT_TOWER_PATH,
) -> dict[datetime, tuple[SensorReading, ...]]:
    """Index good tower samples by timestamp. Bad rows are left out."""
    grouped: dict[datetime, list[SensorReading]] = defaultdict(list)
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            if row.get("quality") != "good":
                continue
            if not row.get("temperature_f") or not row.get("wind_speed_mph"):
                continue
            grouped[datetime.fromisoformat(row["timestamp"])].append(
                SensorReading(
                    height_ft=float(row["height_ft"]),
                    temperature_f=float(row["temperature_f"]),
                    wind_speed_mph=float(row["wind_speed_mph"]),
                    wind_direction_deg=float(row["wind_direction_deg"]),
                )
            )
    return {
        timestamp: _unique_heights(readings)
        for timestamp, readings in grouped.items()
    }


@lru_cache(maxsize=4)
def load_spray_jobs(path: Path = DEFAULT_APPLICATIONS_PATH) -> tuple[SprayJob, ...]:
    jobs: list[SprayJob] = []
    with path.open(encoding="utf-8", newline="") as source:
        for row in csv.DictReader(source):
            jobs.append(
                SprayJob(
                    application_id=row["application_id"],
                    status=row["status"],
                    block_id=row["block_id"],
                    product_id=row["product_id"],
                    earliest_start=_optional_time(row.get("earliest_start", "")),
                    latest_end=_optional_time(row.get("latest_end", "")),
                    duration=timedelta(minutes=int(row["duration_minutes"])),
                    notes=row.get("notes", ""),
                )
            )
    return tuple(jobs)


def assess_hours(
    periods: Sequence[Mapping[str, Any]],
    limits: SprayLimits | None = None,
    tower_by_time: Mapping[datetime, Sequence[SensorReading]] | None = None,
) -> tuple[HourAssessment, ...]:
    """Score each forecast hour. Tower profiles override the single-level forecast."""
    limits = limits or SprayLimits()
    tower_by_time = tower_by_time or {}
    hours: list[HourAssessment] = []
    for period in periods:
        start = datetime.fromisoformat(str(period["startTime"]))
        end = datetime.fromisoformat(str(period["endTime"]))
        wind = parse_wind_mph(str(period.get("windSpeed") or ""))
        temperature = _optional_float(period.get("temperature"))
        precip = _precip_probability(period)
        reasons: list[str] = []
        in_hours = _inside_spray_hours(start, end, limits)
        if not in_hours:
            reasons.append(
                f"Outside spray hours ({format_clock(limits.spray_start)}–"
                f"{format_clock(limits.spray_end)})."
            )
        if precip is not None and precip >= limits.max_precip_probability:
            reasons.append(f"Precipitation chance is {precip:.0f}%.")

        profile = _tower_sample(tower_by_time, start, end) if in_hours else None
        inversion_checked = profile is not None
        if profile is not None:
            wind = max(sensor.wind_speed_mph for sensor in profile)
            temperature = max(sensor.temperature_f for sensor in profile)
            assessment = _assess_profile(profile, limits)
            if assessment.status != Status.GO:
                reasons.extend(alert.title for alert in assessment.alerts)
        elif in_hours:
            if wind is None:
                reasons.append("Forecast wind is missing.")
            elif wind < limits.min_wind_mph or wind > limits.max_wind_mph:
                reasons.append(
                    f"Wind is {wind:.0f} mph, outside "
                    f"{limits.min_wind_mph:g}–{limits.max_wind_mph:g} mph."
                )
            if temperature is None:
                reasons.append("Forecast temperature is missing.")

        if (
            in_hours
            and temperature is not None
            and temperature > limits.max_temp_f
        ):
            reasons.append(
                f"Temperature is {temperature:.0f}°F, above the "
                f"{limits.max_temp_f:g}°F label limit."
            )

        hours.append(
            HourAssessment(
                start=start,
                end=end,
                suitable=not reasons,
                inversion_checked=inversion_checked and not reasons,
                wind_mph=wind,
                temperature_f=temperature,
                reasons=tuple(reasons),
            )
        )
    hours.sort(key=lambda hour: hour.start)
    return tuple(hours)


def find_spray_windows(
    hours: Sequence[HourAssessment],
    minimum: timedelta = timedelta(hours=2),
    limits: SprayLimits | None = None,
) -> tuple[SprayWindow, ...]:
    """Collapse consecutive suitable hours into windows long enough to spray."""
    limits = limits or SprayLimits()
    ordered = tuple(sorted(hours, key=lambda hour: hour.start))
    windows: list[SprayWindow] = []
    run: list[HourAssessment] = []

    def flush() -> None:
        if not run:
            return
        start = run[0].start
        end = run[-1].end
        if end - start >= minimum:
            windows.append(
                SprayWindow(
                    start=start,
                    end=end,
                    inversion_checked=all(hour.inversion_checked for hour in run),
                    likelihood=schedule_likelihood(start, end),
                    opens_because=_edge_reason(ordered, start, "start", limits),
                    closes_because=_edge_reason(ordered, end, "end", limits),
                )
            )
        run.clear()

    for hour in ordered:
        if not hour.suitable:
            flush()
            continue
        if run and hour.start != run[-1].end:
            flush()
        run.append(hour)
    flush()
    return tuple(windows)


def schedule_likelihood(start: datetime, end: datetime) -> str:
    """Weekday spraying is common. Saturday is possible. Sunday is less common.

    A window that misses 7 AM–2 PM is a step less likely, because those are
    the usual application hours.
    """
    if start.weekday() < 5:
        rank = 2
    elif start.weekday() == 5:
        rank = 1
    else:
        rank = 0
    common_start = start.replace(hour=7, minute=0, second=0, microsecond=0)
    common_end = start.replace(hour=14, minute=0, second=0, microsecond=0)
    if not (start < common_end and end > common_start) and rank > 0:
        rank -= 1
    return ("Less common", "Possible", "Common")[rank]


def alert_for_go(
    windows: Sequence[SprayWindow],
    moment: datetime,
    duration: timedelta = timedelta(hours=2),
) -> NextWindowAlert:
    """After a Go, point at the following suitable window.

    A Go that lands inside a window uses that window for the spray. The alert
    is the next window after it ends.
    """
    current = next(
        (window for window in windows if window.start <= moment < window.end),
        None,
    )
    cursor = current.end if current is not None else moment
    upcoming = next(
        (window for window in windows if window.start >= cursor),
        None,
    )
    push = push_text(upcoming, duration, "Go") if upcoming is not None else ""
    return NextWindowAlert(
        go_given_at=moment,
        current_window=current,
        next_window=upcoming,
        message=_alert_message(moment, current, upcoming, duration),
        push=push,
    )


def first_fitting_window(
    windows: Sequence[SprayWindow],
    earliest: datetime,
    latest: datetime,
    duration: timedelta,
) -> SprayWindow | None:
    """Return the first window that can hold the job inside its planned dates."""
    for window in windows:
        overlap_start = max(window.start, earliest)
        overlap_end = min(window.end, latest)
        if overlap_end - overlap_start >= duration:
            return window
    return None


def predict_spray_windows(
    limits: SprayLimits | None = None,
    forecast_path: Path = DEFAULT_FORECAST_PATH,
    tower_path: Path = DEFAULT_TOWER_PATH,
) -> tuple[SprayWindow, ...]:
    limits = limits or SprayLimits()
    hours = assess_hours(
        load_forecast_periods(forecast_path),
        limits,
        load_tower_index(tower_path) if tower_path.exists() else {},
    )
    return find_spray_windows(hours, limits.minimum_window, limits)


def _alert_message(
    moment: datetime,
    current: SprayWindow | None,
    upcoming: SprayWindow | None,
    duration: timedelta,
) -> str:
    when = f"{moment:%a} {format_clock(moment)}"
    if upcoming is None:
        return f"Go at {when}. No later window."

    start_by = latest_start(upcoming, duration)
    start_by_text = f" Start by {format_clock(start_by)}." if start_by else ""
    why = window_why(upcoming)
    why_text = f" {why}." if why else ""
    held = ""
    if current is not None:
        held = f" This spray runs until {format_clock(current.end)}."
    return (
        f"Go at {when}.{held} Next window {format_window_span(upcoming)}."
        f"{start_by_text} {upcoming.likelihood}. {confidence_marker(upcoming)}."
        f"{why_text}"
    )


def _assess_profile(readings: Sequence[SensorReading], limits: SprayLimits):
    thresholds = RiskThresholds(
        minimum_wind_mph=limits.min_wind_mph,
        maximum_wind_mph=limits.max_wind_mph,
    )
    if len(readings) >= 3:
        return assess_multi_height_risk(readings, thresholds=thresholds)
    return assess_spray_risk(
        _reading_from_outer_sensors(readings),
        thresholds=thresholds,
    )


def _reading_from_outer_sensors(readings: Sequence[SensorReading]) -> WeatherReading:
    ordered = sorted(readings, key=lambda item: item.height_ft)
    lower, upper = ordered[0], ordered[-1]
    return WeatherReading(
        lower_temp_f=lower.temperature_f,
        upper_temp_f=upper.temperature_f,
        lower_wind_mph=lower.wind_speed_mph,
        upper_wind_mph=upper.wind_speed_mph,
        lower_direction_deg=lower.wind_direction_deg,
        upper_direction_deg=upper.wind_direction_deg,
        lower_height_ft=lower.height_ft,
        upper_height_ft=upper.height_ft,
    )


def _tower_sample(
    tower_by_time: Mapping[datetime, Sequence[SensorReading]],
    start: datetime,
    end: datetime,
) -> tuple[SensorReading, ...] | None:
    if not tower_by_time:
        return None
    target = start + (end - start) / 2
    if target in tower_by_time and len(tower_by_time[target]) >= 2:
        return tuple(tower_by_time[target])
    candidates = [
        timestamp
        for timestamp, readings in tower_by_time.items()
        if start <= timestamp < end and len(readings) >= 2
    ]
    if not candidates:
        return None
    nearest = min(candidates, key=lambda timestamp: abs(timestamp - target))
    return tuple(tower_by_time[nearest])


def _inside_spray_hours(start: datetime, end: datetime, limits: SprayLimits) -> bool:
    start_clock = start.timetz().replace(tzinfo=None)
    end_clock = end.timetz().replace(tzinfo=None)
    if end_clock <= start_clock:
        return False
    return start_clock >= limits.spray_start and end_clock <= limits.spray_end


def _edge_reason(
    hours: Sequence[HourAssessment],
    boundary: datetime,
    side: str,
    limits: SprayLimits,
) -> str:
    """Why the window opens late or closes early, from the hour on that edge."""
    if side == "start":
        hour = next((item for item in hours if item.end == boundary), None)
    else:
        hour = next((item for item in hours if item.start == boundary), None)
    if hour is None or hour.suitable:
        return ""
    if not _inside_spray_hours(hour.start, hour.end, limits):
        return ""
    kind = _edge_kind(hour, limits)
    if kind in {"", "hours"}:
        return ""
    return _edge_phrase(kind, boundary, side, limits)


def _edge_kind(hour: HourAssessment, limits: SprayLimits) -> str:
    kinds: list[str] = []
    for reason in hour.reasons:
        kind = _block_kind(reason)
        if kind == "wind_band":
            kind = _wind_side(reason, limits)
        kinds.append(kind)
    for kind in (
        "inversion",
        "calm",
        "wind",
        "temp",
        "rain",
        "direction",
        "shear",
        "missing",
        "other",
        "hours",
    ):
        if kind in kinds:
            return kind
    return ""


def _block_kind(reason: str) -> str:
    text = reason.lower()
    if "inversion" in text:
        return "inversion"
    if "too calm" in text or "below the" in text:
        return "calm"
    if "too strong" in text:
        return "wind"
    if "wind is" in text and "mph" in text:
        return "wind_band"
    if "temperature" in text:
        return "temp"
    if "precipitation" in text or text.startswith("rain"):
        return "rain"
    if "direction" in text:
        return "direction"
    if "shear" in text or "speed" in text:
        return "shear"
    if "outside spray" in text:
        return "hours"
    if "missing" in text:
        return "missing"
    return "other"


def _wind_side(reason: str, limits: SprayLimits) -> str:
    numbers = [float(match) for match in _WIND_SPEED.findall(reason)]
    if numbers and numbers[0] < limits.min_wind_mph:
        return "calm"
    return "wind"


def _edge_phrase(kind: str, boundary: datetime, side: str, limits: SprayLimits) -> str:
    clock = format_clock(boundary)
    if kind == "inversion":
        head = "Inversion"
    elif kind == "calm":
        head = f"Wind under {limits.min_wind_mph:g} mph"
    elif kind == "wind":
        head = f"Wind above {limits.max_wind_mph:g} mph"
    elif kind == "temp":
        if side == "end":
            return f"Temperature passes {limits.max_temp_f:g}°F after {clock}"
        return f"Temperature above {limits.max_temp_f:g}°F until {clock}"
    elif kind == "rain":
        head = "Rain"
    elif kind == "direction":
        head = "Direction shear"
    elif kind == "shear":
        head = "Wind shear"
    else:
        return ""
    if side == "start":
        return f"{head} until {clock}"
    return f"{head} after {clock}"


def _unique_heights(readings: Sequence[SensorReading]) -> tuple[SensorReading, ...]:
    chosen: dict[float, SensorReading] = {}
    for reading in sorted(readings, key=lambda item: item.height_ft):
        chosen.setdefault(reading.height_ft, reading)
    return tuple(chosen.values())


def _precip_probability(period: Mapping[str, Any]) -> float | None:
    raw = period.get("probabilityOfPrecipitation") or {}
    if not isinstance(raw, Mapping):
        return None
    return _optional_float(raw.get("value"))


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _optional_time(value: str) -> datetime | None:
    text = value.strip()
    if not text:
        return None
    return datetime.fromisoformat(text)

