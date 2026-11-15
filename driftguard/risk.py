"""Explainable, deterministic spray-risk rules."""

from __future__ import annotations

from collections.abc import Sequence

from .models import (
    Alert,
    ApplicationSettings,
    Assessment,
    DropletSize,
    RiskFlags,
    RiskThresholds,
    SensorReading,
    Status,
    Volatility,
    WeatherReading,
)


def circular_direction_difference(first_deg: float, second_deg: float) -> float:
    """Return the smallest angle between two headings (0 to 180 degrees)."""
    difference = abs((first_deg % 360) - (second_deg % 360))
    return min(difference, 360 - difference)


def evaluate_weather_flags(
    reading: WeatherReading, thresholds: RiskThresholds | None = None
) -> RiskFlags:
    """Evaluate the five core weather hazards without assigning a status."""
    thresholds = thresholds or RiskThresholds()
    speeds = (reading.lower_wind_mph, reading.upper_wind_mph)
    return RiskFlags(
        inversion=reading.upper_temp_f > reading.lower_temp_f,
        wind_below_minimum=any(
            speed < thresholds.minimum_wind_mph for speed in speeds
        ),
        wind_above_maximum=any(
            speed > thresholds.maximum_wind_mph for speed in speeds
        ),
        wind_speed_shear=(
            abs(reading.upper_wind_mph - reading.lower_wind_mph)
            >= thresholds.speed_shear_mph
        ),
        wind_direction_shear=(
            circular_direction_difference(
                reading.lower_direction_deg, reading.upper_direction_deg
            )
            >= thresholds.direction_shear_deg
        ),
    )


def _wind_band_alerts(
    reading: WeatherReading, thresholds: RiskThresholds
) -> list[Alert]:
    alerts: list[Alert] = []
    levels = (
        ("lower", reading.lower_height_ft, reading.lower_wind_mph),
        ("upper", reading.upper_height_ft, reading.upper_wind_mph),
    )

    for level, height, speed in levels:
        if speed < thresholds.minimum_wind_mph:
            alerts.append(
                Alert(
                    code=f"{level}_wind_low",
                    status=Status.STOP,
                    title=f"Wind too calm at {height:g} ft",
                    explanation=(
                        f"Wind is {speed:.1f} mph at {height:g} ft, below the "
                        f"{thresholds.minimum_wind_mph:g} mph minimum. Fine droplets "
                        "can remain suspended and move unpredictably."
                    ),
                )
            )
        elif speed > thresholds.maximum_wind_mph:
            alerts.append(
                Alert(
                    code=f"{level}_wind_high",
                    status=Status.STOP,
                    title=f"Wind too strong at {height:g} ft",
                    explanation=(
                        f"Wind is {speed:.1f} mph at {height:g} ft, above the "
                        f"{thresholds.maximum_wind_mph:g} mph maximum. Strong wind can "
                        "carry spray beyond the target."
                    ),
                )
            )
    return alerts


def assess_spray_risk(
    reading: WeatherReading,
    application: ApplicationSettings | None = None,
    thresholds: RiskThresholds | None = None,
) -> Assessment:
    """Assess current conditions; this does not replace product-label requirements."""
    application = application or ApplicationSettings()
    thresholds = thresholds or RiskThresholds()
    flags = evaluate_weather_flags(reading, thresholds)
    alerts = _wind_band_alerts(reading, thresholds)

    inversion_delta = reading.upper_temp_f - reading.lower_temp_f
    speed_delta = abs(reading.upper_wind_mph - reading.lower_wind_mph)
    direction_delta = circular_direction_difference(
        reading.lower_direction_deg, reading.upper_direction_deg
    )

    if flags.inversion:
        alerts.append(
            Alert(
                code="temperature_inversion",
                status=Status.STOP,
                title="Temperature inversion detected",
                explanation=(
                    f"Air at {reading.upper_height_ft:g} ft is {inversion_delta:.1f}°F "
                    f"warmer than at {reading.lower_height_ft:g} ft. Spray can become "
                    "trapped near the ground and travel sideways."
                ),
            )
        )

    if flags.wind_speed_shear:
        alerts.append(
            Alert(
                code="speed_shear",
                status=Status.CAUTION,
                title="Wind speed changes sharply with height",
                explanation=(
                    f"Wind differs by {speed_delta:.1f} mph between "
                    f"{reading.lower_height_ft:g} ft and {reading.upper_height_ft:g} ft "
                    f"(caution threshold: {thresholds.speed_shear_mph:g} mph)."
                ),
            )
        )

    if flags.wind_direction_shear:
        alerts.append(
            Alert(
                code="direction_shear",
                status=Status.CAUTION,
                title="Wind direction changes with height",
                explanation=(
                    f"Wind direction shifts {direction_delta:.0f}° between sensor "
                    f"heights (caution threshold: {thresholds.direction_shear_deg:g}°). "
                    "Spray may move in a direction that is not apparent at ground level."
                ),
            )
        )

    base_status = max((alert.status for alert in alerts), default=Status.GO)
    modifiers: list[str] = []
    if application.volatility == Volatility.HIGH:
        modifiers.append("high product volatility")
    if application.droplet_size == DropletSize.FINE:
        modifiers.append("fine droplets")

    status = base_status
    if modifiers and status < Status.STOP:
        status = Status(status + 1)
        alerts.append(
            Alert(
                code="application_risk",
                status=status,
                title="Application setup increases drift risk",
                explanation=(
                    f"{' and '.join(modifiers).capitalize()} increase drift potential, "
                    f"so the recommendation is raised from {base_status.name} to "
                    f"{status.name}."
                ),
            )
        )

    recommendations = {
        Status.GO: (
            "Conditions are within the configured weather limits. Verify the product "
            "label, buffer zones, equipment, and conditions at the block before spraying."
        ),
        Status.CAUTION: (
            "Pause and verify conditions across the block. Consider coarser droplets or "
            "a lower-volatility product, and reassess before spraying."
        ),
        Status.STOP: (
            "Do not begin or continue spraying under these readings. Wait for conditions "
            "to improve, then take a new assessment."
        ),
    }
    return Assessment(
        status=status,
        alerts=tuple(alerts),
        flags=flags,
        inversion_delta_f=inversion_delta,
        wind_speed_delta_mph=speed_delta,
        wind_direction_delta_deg=direction_delta,
        recommendation=recommendations[status],
    )


def assess_multi_height_risk(
    readings: Sequence[SensorReading],
    application: ApplicationSettings | None = None,
    thresholds: RiskThresholds | None = None,
) -> Assessment:
    """Assess every sensor and every adjacent atmospheric layer."""
    if len(readings) < 2:
        raise ValueError("At least two sensor heights are required")

    application = application or ApplicationSettings()
    thresholds = thresholds or RiskThresholds()
    ordered = sorted(readings, key=lambda item: item.height_ft)
    if len({item.height_ft for item in ordered}) != len(ordered):
        raise ValueError("Sensor heights must be unique")

    alerts: list[Alert] = []
    below_minimum = False
    above_maximum = False
    for sensor in ordered:
        if sensor.wind_speed_mph < thresholds.minimum_wind_mph:
            below_minimum = True
            alerts.append(
                Alert(
                    code=f"wind_low_{sensor.height_ft:g}ft",
                    status=Status.STOP,
                    title=f"Wind too calm at {sensor.height_ft:g} ft",
                    explanation=(
                        f"Wind is {sensor.wind_speed_mph:.1f} mph at "
                        f"{sensor.height_ft:g} ft, below the "
                        f"{thresholds.minimum_wind_mph:g} mph minimum."
                    ),
                )
            )
        elif sensor.wind_speed_mph > thresholds.maximum_wind_mph:
            above_maximum = True
            alerts.append(
                Alert(
                    code=f"wind_high_{sensor.height_ft:g}ft",
                    status=Status.STOP,
                    title=f"Wind too strong at {sensor.height_ft:g} ft",
                    explanation=(
                        f"Wind is {sensor.wind_speed_mph:.1f} mph at "
                        f"{sensor.height_ft:g} ft, above the "
                        f"{thresholds.maximum_wind_mph:g} mph maximum."
                    ),
                )
            )

    inversion_deltas: list[float] = []
    speed_deltas: list[float] = []
    direction_deltas: list[float] = []
    inversion = False
    speed_shear = False
    direction_shear = False

    for lower, upper in zip(ordered, ordered[1:]):
        temperature_delta = upper.temperature_f - lower.temperature_f
        inversion_deltas.append(temperature_delta)

        if temperature_delta > 0:
            inversion = True
            alerts.append(
                Alert(
                    code=f"inversion_{lower.height_ft:g}_{upper.height_ft:g}ft",
                    status=Status.STOP,
                    title=(
                        f"Inversion between {lower.height_ft:g} and "
                        f"{upper.height_ft:g} ft"
                    ),
                    explanation=(
                        f"Temperature rises {temperature_delta:.1f}°F from "
                        f"{lower.height_ft:g} to {upper.height_ft:g} ft, indicating "
                        "a trapping layer."
                    ),
                )
            )

    sensor_pairs = [
        (lower, upper)
        for index, lower in enumerate(ordered)
        for upper in ordered[index + 1 :]
    ]
    speed_changes = [
        (abs(upper.wind_speed_mph - lower.wind_speed_mph), lower, upper)
        for lower, upper in sensor_pairs
    ]
    direction_changes = [
        (
            circular_direction_difference(
                lower.wind_direction_deg, upper.wind_direction_deg
            ),
            lower,
            upper,
        )
        for lower, upper in sensor_pairs
    ]
    speed_delta, speed_lower, speed_upper = max(speed_changes, key=lambda item: item[0])
    direction_delta, direction_lower, direction_upper = max(
        direction_changes, key=lambda item: item[0]
    )
    speed_deltas.append(speed_delta)
    direction_deltas.append(direction_delta)

    if speed_delta >= thresholds.speed_shear_mph:
        speed_shear = True
        alerts.append(
            Alert(
                code=f"speed_shear_{speed_lower.height_ft:g}_{speed_upper.height_ft:g}ft",
                status=Status.CAUTION,
                title=(
                    f"Wind speed shear between {speed_lower.height_ft:g} and "
                    f"{speed_upper.height_ft:g} ft"
                ),
                explanation=(
                    f"The largest speed change is {speed_delta:.1f} mph; the caution "
                    f"threshold is {thresholds.speed_shear_mph:g} mph."
                ),
            )
        )

    if direction_delta >= thresholds.direction_shear_deg:
        direction_shear = True
        alerts.append(
            Alert(
                code=(
                    f"direction_shear_{direction_lower.height_ft:g}_"
                    f"{direction_upper.height_ft:g}ft"
                ),
                status=Status.CAUTION,
                title=(
                    f"Wind direction shear between {direction_lower.height_ft:g} and "
                    f"{direction_upper.height_ft:g} ft"
                ),
                explanation=(
                    f"The largest direction change is {direction_delta:.0f}°; the "
                    f"caution threshold is {thresholds.direction_shear_deg:g}°."
                ),
            )
        )

    flags = RiskFlags(
        inversion=inversion,
        wind_below_minimum=below_minimum,
        wind_above_maximum=above_maximum,
        wind_speed_shear=speed_shear,
        wind_direction_shear=direction_shear,
    )
    base_status = max((alert.status for alert in alerts), default=Status.GO)
    modifiers: list[str] = []
    if application.volatility == Volatility.HIGH:
        modifiers.append("high product volatility")
    if application.droplet_size == DropletSize.FINE:
        modifiers.append("fine droplets")

    status = base_status
    if modifiers and status < Status.STOP:
        status = Status(status + 1)
        alerts.append(
            Alert(
                code="application_risk",
                status=status,
                title="Application setup increases drift risk",
                explanation=(
                    f"{' and '.join(modifiers).capitalize()} increase drift potential, "
                    f"raising the recommendation from {base_status.name} to {status.name}."
                ),
            )
        )

    recommendations = {
        Status.GO: (
            "All measured layers are within the configured limits. Verify the product "
            "label and conditions across the block before spraying."
        ),
        Status.CAUTION: (
            "A vertical wind change was detected. Pause, verify conditions across the "
            "block, and reassess before spraying."
        ),
        Status.STOP: (
            "Do not begin or continue spraying under these readings. Wait for conditions "
            "to improve, then take a new assessment."
        ),
    }
    return Assessment(
        status=status,
        alerts=tuple(alerts),
        flags=flags,
        inversion_delta_f=max(inversion_deltas),
        wind_speed_delta_mph=max(speed_deltas),
        wind_direction_delta_deg=max(direction_deltas),
        recommendation=recommendations[status],
    )
