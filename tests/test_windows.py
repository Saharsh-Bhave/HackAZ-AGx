"""Tests for spray-window prediction and the post-GO alert."""

from datetime import datetime, timedelta

from driftguard.models import SensorReading
from driftguard.windows import (
    HourAssessment,
    SprayLimits,
    alert_for_go,
    assess_hours,
    find_spray_windows,
    first_fitting_window,
    format_clock,
    latest_start,
    parse_wind_mph,
    predict_spray_windows,
    push_text,
)


def _period(
    start: str,
    wind: str = "5 mph",
    temperature: float = 60,
    precip: float = 0,
) -> dict:
    start_at = datetime.fromisoformat(start)
    return {
        "startTime": start_at.isoformat(),
        "endTime": (start_at + timedelta(hours=1)).isoformat(),
        "temperature": temperature,
        "windSpeed": wind,
        "probabilityOfPrecipitation": {"value": precip},
    }


def _span(
    day: str,
    hours: range,
    suitable: bool,
    reason: str = "Wind too strong at 30 ft",
    checked: bool | None = None,
) -> list:
    rows = []
    for hour in hours:
        start = datetime.fromisoformat(f"{day}T{hour:02d}:00:00-08:00")
        rows.append(
            HourAssessment(
                start=start,
                end=start + timedelta(hours=1),
                suitable=suitable,
                inversion_checked=suitable if checked is None else checked,
                wind_mph=5,
                temperature_f=60,
                reasons=() if suitable else (reason,),
            )
        )
    return rows


def test_parse_wind_uses_the_top_of_a_range() -> None:
    assert parse_wind_mph("7 to 10 mph") == 10
    assert parse_wind_mph("3 mph") == 3
    assert parse_wind_mph("Calm") is None


def test_night_rain_and_wind_are_not_suitable() -> None:
    hours = assess_hours(
        [
            _period("2026-11-15T02:00:00-08:00"),
            _period("2026-11-15T11:00:00-08:00", precip=40),
            _period("2026-11-15T12:00:00-08:00", wind="14 mph"),
            _period("2026-11-15T13:00:00-08:00", temperature=92),
            _period("2026-11-15T14:00:00-08:00"),
        ],
        SprayLimits(max_temp_f=90),
    )

    assert [hour.suitable for hour in hours] == [False, False, False, False, True]
    assert hours[0].reasons[0].startswith("Outside spray hours")
    assert "Precipitation" in hours[1].reasons[0]
    assert "Wind" in hours[2].reasons[0]
    assert "Temperature" in hours[3].reasons[0]
    assert hours[4].inversion_checked is False


def test_tower_inversion_blocks_an_hour_the_forecast_would_allow() -> None:
    start = datetime.fromisoformat("2026-11-12T07:00:00-08:00")
    profile = (
        SensorReading(5, 50, 5, 90),
        SensorReading(30, 55, 8, 180),
    )
    hours = assess_hours(
        [_period("2026-11-12T07:00:00-08:00", wind="6 mph")],
        tower_by_time={start + timedelta(minutes=30): profile},
    )

    assert hours[0].suitable is False
    assert any("inversion" in reason.lower() for reason in hours[0].reasons)


def test_short_runs_are_dropped_and_gaps_split_windows() -> None:
    hours = (
        _span("2026-11-15", range(10, 14), True)
        + _span("2026-11-15", range(14, 15), False)
        + _span("2026-11-15", range(15, 17), True)
    )
    windows = find_spray_windows(hours, minimum=timedelta(hours=2))

    assert len(windows) == 2
    assert windows[0].start.hour == 10
    assert windows[0].end.hour == 14
    assert windows[1].start.hour == 15
    assert windows[1].inversion_checked is True


def test_one_suitable_hour_is_not_a_window() -> None:
    windows = find_spray_windows(
        _span("2026-11-15", range(12, 13), True),
        minimum=timedelta(hours=2),
    )

    assert windows == ()


def test_go_inside_a_window_alerts_the_following_window() -> None:
    windows = find_spray_windows(
        _span("2026-11-15", range(10, 14), True)
        + _span("2026-11-16", range(9, 12), True)
    )
    moment = datetime.fromisoformat("2026-11-15T11:30:00-08:00")
    alert = alert_for_go(windows, moment)

    assert alert.current_window is windows[0]
    assert alert.next_window is windows[1]
    assert "Next window Mon 9 AM–12 PM" in alert.message
    assert "Start by 10 AM" in alert.message
    assert alert.push == "Go Mon 9 AM–12 PM. Start by 10 AM. Tower."
    assert alert.push != alert.message


def test_go_between_windows_alerts_the_upcoming_one() -> None:
    windows = find_spray_windows(
        _span("2026-11-15", range(10, 12), True)
        + _span("2026-11-16", range(9, 12), True)
    )
    moment = datetime.fromisoformat("2026-11-15T18:00:00-08:00")
    alert = alert_for_go(windows, moment)

    assert alert.current_window is None
    assert alert.next_window is windows[1]


def test_go_after_the_last_window_has_no_next_window() -> None:
    windows = find_spray_windows(_span("2026-11-15", range(10, 12), True))
    moment = datetime.fromisoformat("2026-11-16T09:00:00-08:00")
    alert = alert_for_go(windows, moment)

    assert alert.next_window is None
    assert alert.message == "Go at Mon 9 AM. No later window."
    assert alert.push == ""


def test_fitting_window_must_cover_the_job() -> None:
    windows = find_spray_windows(_span("2026-11-15", range(10, 16), True))
    earliest = datetime.fromisoformat("2026-11-15T14:00:00-08:00")
    latest = datetime.fromisoformat("2026-11-15T18:00:00-08:00")

    assert (
        first_fitting_window(windows, earliest, latest, timedelta(hours=2))
        is windows[0]
    )
    assert (
        first_fitting_window(windows, earliest, latest, timedelta(hours=5)) is None
    )


def test_latest_start_is_the_job_constraint() -> None:
    windows = find_spray_windows(_span("2026-11-15", range(7, 16), True))
    start_by = latest_start(windows[0], timedelta(hours=2))

    assert start_by is not None
    assert format_clock(start_by) == "2 PM"
    assert format_clock(latest_start(windows[0], timedelta(minutes=90))) == "2:30 PM"


def test_edge_reason_names_the_inversion_that_holds_the_window() -> None:
    hours = (
        _span("2026-11-12", range(4, 9), False, "Inversion between 5 and 30 ft")
        + _span("2026-11-12", range(9, 16), True)
        + _span("2026-11-12", range(16, 22), False, "Wind too strong at 30 ft")
    )
    window = find_spray_windows(hours)[0]

    assert window.opens_because == "Inversion until 9 AM"
    assert window.closes_because == "Wind above 10 mph after 4 PM"
    assert window.likelihood == "Common"


def test_sunday_midday_is_less_common_and_forecast_push_says_inversion_unseen() -> None:
    window = find_spray_windows(
        _span("2026-11-15", range(7, 16), True, checked=False)
    )[0]

    assert window.likelihood == "Less common"
    assert (
        push_text(window, timedelta(hours=2), "A4 B1")
        == "A4 B1 Sun 7 AM–4 PM. Start by 2 PM. Inversion unseen."
    )


def test_plan_end_pulls_the_start_by_time_forward() -> None:
    window = find_spray_windows(
        _span("2026-11-15", range(4, 22), True, checked=False)
    )[0]
    earliest = datetime.fromisoformat("2026-11-15T06:00:00-08:00")
    latest = datetime.fromisoformat("2026-11-15T18:00:00-08:00")

    assert format_clock(latest_start(window, timedelta(hours=2), earliest, latest)) == "4 PM"
    assert (
        push_text(window, timedelta(hours=2), "A4 B1", earliest, latest)
        == "A4 B1 Sun 6 AM–6 PM. Start by 4 PM. Inversion unseen."
    )


def test_recorded_hazards_fall_outside_spray_windows() -> None:
    windows = predict_spray_windows()
    blocked = (
        "2026-11-11T05:30:00-08:00",
        "2026-11-12T07:00:00-08:00",
        "2026-11-13T14:00:00-08:00",
        "2026-11-16T14:00:00-08:00",
    )
    for stamp in blocked:
        moment = datetime.fromisoformat(stamp)
        assert not any(window.start <= moment < window.end for window in windows), stamp


def test_safe_midday_go_alerts_a_later_window() -> None:
    windows = predict_spray_windows()
    moment = datetime.fromisoformat("2026-11-11T13:00:00-08:00")
    alert = alert_for_go(windows, moment)

    assert alert.current_window is not None
    assert alert.next_window is not None
    assert alert.next_window.start >= alert.current_window.end
    assert alert.current_window.inversion_checked is True
