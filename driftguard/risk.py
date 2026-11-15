"""Explainable, deterministic spray-risk rules."""

from __future__ import annotations

from .models import (
    Alert,
    ApplicationSettings,
    Assessment,
    DropletSize,
    RiskThresholds,
    Status,
    Volatility,
    WeatherReading,
)


def circular_direction_difference(first_deg: float, second_deg: float) -> float:
    """Return the smallest angle between two headings (0 to 180 degrees)."""
    difference = abs((first_deg % 360) - (second_deg % 360))
    return min(difference, 360 - difference)


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
    alerts = _wind_band_alerts(reading, thresholds)

    inversion_delta = reading.upper_temp_f - reading.lower_temp_f
    speed_delta = abs(reading.upper_wind_mph - reading.lower_wind_mph)
    direction_delta = circular_direction_difference(
        reading.lower_direction_deg, reading.upper_direction_deg
    )

    if inversion_delta > 0:
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

    if speed_delta >= thresholds.speed_shear_mph:
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

    if direction_delta >= thresholds.direction_shear_deg:
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
        inversion_delta_f=inversion_delta,
        wind_speed_delta_mph=speed_delta,
        wind_direction_delta_deg=direction_delta,
        recommendation=recommendations[status],
    )
