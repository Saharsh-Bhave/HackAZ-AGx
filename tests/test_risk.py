"""Tests for the deterministic spray-risk engine."""

from driftguard.models import (
    ApplicationSettings,
    DropletSize,
    Status,
    Volatility,
    WeatherReading,
)
from driftguard.risk import assess_spray_risk, circular_direction_difference


def reading(**overrides: float) -> WeatherReading:
    values = {
        "lower_temp_f": 70.0,
        "upper_temp_f": 66.0,
        "lower_wind_mph": 5.0,
        "upper_wind_mph": 7.0,
        "lower_direction_deg": 350.0,
        "upper_direction_deg": 10.0,
    }
    values.update(overrides)
    return WeatherReading(**values)


def alert_codes(result) -> set[str]:
    return {alert.code for alert in result.alerts}


def test_safe_conditions_are_go() -> None:
    result = assess_spray_risk(reading())

    assert result.status == Status.GO
    assert result.alerts == ()


def test_inversion_is_stop() -> None:
    result = assess_spray_risk(
        reading(lower_temp_f=60.0, upper_temp_f=64.0)
    )

    assert result.status == Status.STOP
    assert "temperature_inversion" in alert_codes(result)
    assert result.inversion_delta_f == 4.0


def test_low_wind_at_either_height_is_stop() -> None:
    result = assess_spray_risk(reading(upper_wind_mph=2.9))

    assert result.status == Status.STOP
    assert "upper_wind_low" in alert_codes(result)


def test_high_wind_at_either_height_is_stop() -> None:
    result = assess_spray_risk(reading(lower_wind_mph=10.1))

    assert result.status == Status.STOP
    assert "lower_wind_high" in alert_codes(result)


def test_wind_band_boundaries_are_allowed() -> None:
    result = assess_spray_risk(
        reading(lower_wind_mph=3.0, upper_wind_mph=10.0)
    )

    assert result.status == Status.CAUTION
    assert "speed_shear" in alert_codes(result)
    assert "lower_wind_low" not in alert_codes(result)
    assert "upper_wind_high" not in alert_codes(result)


def test_speed_shear_is_caution() -> None:
    result = assess_spray_risk(
        reading(lower_wind_mph=4.0, upper_wind_mph=9.0)
    )

    assert result.status == Status.CAUTION
    assert "speed_shear" in alert_codes(result)


def test_direction_shear_is_caution() -> None:
    result = assess_spray_risk(
        reading(lower_direction_deg=20.0, upper_direction_deg=65.0)
    )

    assert result.status == Status.CAUTION
    assert "direction_shear" in alert_codes(result)


def test_direction_difference_wraps_through_north() -> None:
    assert circular_direction_difference(350, 10) == 20
    assert circular_direction_difference(10, 350) == 20


def test_high_volatility_raises_go_to_caution() -> None:
    application = ApplicationSettings(volatility=Volatility.HIGH)
    result = assess_spray_risk(reading(), application)

    assert result.status == Status.CAUTION
    assert "application_risk" in alert_codes(result)


def test_fine_droplets_raise_caution_to_stop() -> None:
    application = ApplicationSettings(
        volatility=Volatility.LOW,
        droplet_size=DropletSize.FINE,
    )
    result = assess_spray_risk(
        reading(lower_direction_deg=0.0, upper_direction_deg=50.0),
        application,
    )

    assert result.status == Status.STOP
    assert "direction_shear" in alert_codes(result)
    assert "application_risk" in alert_codes(result)
