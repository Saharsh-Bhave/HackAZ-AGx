"""Tests for the three-height presentation mode."""

from driftguard.models import SensorReading, Status, WeatherReading
from driftguard.risk import assess_multi_height_risk, assess_spray_risk


def sensor(height: float, temp: float, speed: float, direction: float) -> SensorReading:
    return SensorReading(height, temp, speed, direction)


def test_three_safe_sensors_are_go() -> None:
    result = assess_multi_height_risk(
        [
            sensor(5, 65, 5, 300),
            sensor(15, 63, 6, 310),
            sensor(30, 60, 7, 315),
        ]
    )

    assert result.status == Status.GO
    assert not result.flags.inversion


def test_middle_sensor_reveals_hidden_inversion_layer() -> None:
    outer_only = assess_spray_risk(
        WeatherReading(60, 59, 5, 6, 180, 190)
    )
    three_sensors = assess_multi_height_risk(
        [
            sensor(5, 60, 5, 180),
            sensor(15, 62, 5.5, 185),
            sensor(30, 59, 6, 190),
        ]
    )

    assert outer_only.status == Status.GO
    assert three_sensors.status == Status.STOP
    assert three_sensors.flags.inversion


def test_middle_sensor_outside_wind_band_is_stop() -> None:
    result = assess_multi_height_risk(
        [
            sensor(5, 65, 5, 300),
            sensor(15, 63, 11, 305),
            sensor(30, 60, 7, 310),
        ]
    )

    assert result.status == Status.STOP
    assert result.flags.wind_above_maximum


def test_shear_uses_largest_difference_across_all_heights() -> None:
    result = assess_multi_height_risk(
        [
            sensor(5, 65, 4, 350),
            sensor(15, 63, 6, 20),
            sensor(30, 60, 9, 50),
        ]
    )

    assert result.status == Status.CAUTION
    assert result.flags.wind_speed_shear
    assert result.flags.wind_direction_shear
    assert result.wind_speed_delta_mph == 5
    assert result.wind_direction_delta_deg == 60


def test_duplicate_sensor_heights_are_rejected() -> None:
    readings = [
        sensor(5, 65, 5, 300),
        sensor(5, 63, 6, 310),
    ]

    try:
        assess_multi_height_risk(readings)
    except ValueError as error:
        assert "unique" in str(error)
    else:
        raise AssertionError("Expected duplicate heights to be rejected")
