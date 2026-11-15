"""Integration tests for the supplied simulated scenario data."""

from pathlib import Path

from driftguard.data import load_scenarios, load_tower_timeline
from driftguard.risk import evaluate_weather_flags


SCENARIOS_PATH = Path(__file__).parents[1] / "data" / "scenarios.json"


def scenarios_by_id():
    return {scenario.id: scenario for scenario in load_scenarios(SCENARIOS_PATH)}


def test_scenarios_load_lowest_and_highest_valid_heights() -> None:
    scenarios = scenarios_by_id()

    assert scenarios["safe_midday"].reading.lower_height_ft == 5
    assert scenarios["safe_midday"].reading.upper_height_ft == 30
    assert scenarios["sensor_missing_upper"].reading.upper_height_ft == 15


def test_inversion_scenario_sets_inversion_flag() -> None:
    flags = evaluate_weather_flags(
        scenarios_by_id()["hidden_inversion"].reading
    )

    assert flags.inversion
    assert flags.wind_direction_shear


def test_low_and_high_wind_scenarios_set_band_flags() -> None:
    scenarios = scenarios_by_id()

    assert evaluate_weather_flags(
        scenarios["low_wind_no_inversion"].reading
    ).wind_below_minimum
    assert evaluate_weather_flags(
        scenarios["high_wind_aloft"].reading
    ).wind_above_maximum


def test_dedicated_shear_scenarios_set_shear_flags() -> None:
    scenarios = scenarios_by_id()

    assert evaluate_weather_flags(
        scenarios["speed_shear_only"].reading
    ).wind_speed_shear
    assert evaluate_weather_flags(
        scenarios["direction_shear_only"].reading
    ).wind_direction_shear


def test_exact_wind_boundaries_are_not_flagged() -> None:
    scenarios = scenarios_by_id()

    at_three = evaluate_weather_flags(
        scenarios["boundary_wind_3mph"].reading
    )
    at_ten = evaluate_weather_flags(
        scenarios["boundary_wind_10mph"].reading
    )

    assert not at_three.wind_below_minimum
    assert not at_ten.wind_above_maximum


def test_tower_timeline_is_chronological_and_multi_height() -> None:
    timeline = load_tower_timeline()

    assert len(timeline) > 1_000
    assert timeline[0].timestamp < timeline[-1].timestamp
    assert {sensor.height_ft for sensor in timeline[0].sensor_readings} == {
        5,
        15,
        30,
    }


def test_tower_timeline_excludes_non_good_sensor_rows() -> None:
    timeline = load_tower_timeline()
    snapshots = {snapshot.timestamp: snapshot for snapshot in timeline}
    missing_period = snapshots["2026-11-14T03:30:00-08:00"]

    assert {sensor.height_ft for sensor in missing_period.sensor_readings} == {5, 15}
