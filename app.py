"""Streamlit dashboard for Orchard Drift Guard."""

from __future__ import annotations

import json
from datetime import datetime

import streamlit as st

from driftguard.data import load_scenarios
from driftguard.models import (
    ApplicationSettings,
    DropletSize,
    SensorReading,
    Status,
    Volatility,
    WeatherReading,
)
from driftguard.risk import assess_multi_height_risk, assess_spray_risk
from driftguard.storage import assessments_to_csv, get_assessments, save_assessment
from driftguard.windows import (
    alert_for_go,
    confidence_marker,
    first_fitting_window,
    format_clock,
    format_window_span,
    latest_start,
    limits_for_product,
    planned_why,
    load_products,
    load_site,
    load_spray_jobs,
    predict_spray_windows,
    push_text,
    window_why,
)

STATUS_LABEL = {Status.GO: "Go", Status.CAUTION: "Caution", Status.STOP: "Stop"}
STATUS_FILTER = {"All": None, "Go": "GO", "Caution": "CAUTION", "Stop": "STOP"}

st.set_page_config(
    page_title="Orchard Drift Guard",
    page_icon="🌳",
    layout="wide",
    initial_sidebar_state="expanded",
)

SCENARIOS = load_scenarios()
SCENARIO_BY_NAME = {scenario.name: scenario for scenario in SCENARIOS}
TWO_SENSOR_MODE = "2 sensors · 5 + 30 ft"
THREE_SENSOR_MODE = "3 sensors · 5 + 15 + 30 ft"


def sensor_at_height(scenario, height: float):
    return next(
        (
            sensor
            for sensor in scenario.sensor_readings
            if sensor.height_ft == height
        ),
        None,
    )


THREE_SENSOR_SCENARIOS = [
    scenario
    for scenario in SCENARIOS
    if all(sensor_at_height(scenario, height) for height in (5, 15, 30))
]
PRESETS = {}
for scenario in SCENARIOS:
    middle = sensor_at_height(scenario, 15)
    PRESETS[scenario.name] = {
        "lower_temp": scenario.reading.lower_temp_f,
        "upper_temp": scenario.reading.upper_temp_f,
        "lower_wind": scenario.reading.lower_wind_mph,
        "upper_wind": scenario.reading.upper_wind_mph,
        "lower_direction": int(scenario.reading.lower_direction_deg),
        "upper_direction": int(scenario.reading.upper_direction_deg),
        "lower_height": scenario.reading.lower_height_ft,
        "upper_height": scenario.reading.upper_height_ft,
        "middle_temp": middle.temperature_f if middle else 0.0,
        "middle_wind": middle.wind_speed_mph if middle else 0.0,
        "middle_direction": int(middle.wind_direction_deg) if middle else 0,
        "middle_height": middle.height_ft if middle else 15.0,
    }


def apply_preset() -> None:
    for key, value in PRESETS[st.session_state.preset].items():
        st.session_state[key] = value


PRODUCTS = load_products()
PRODUCT_BY_NAME = {product["name"]: product for product in PRODUCTS}
PRODUCT_BY_ID = {product["product_id"]: product for product in PRODUCTS}
SITE = load_site()
_VOLATILITY_BY_LABEL = {
    "low": Volatility.LOW.value,
    "medium": Volatility.MODERATE.value,
    "high": Volatility.HIGH.value,
}


def apply_catalog_product() -> None:
    product = PRODUCT_BY_NAME[st.session_state.product_name]
    st.session_state.volatility = _VOLATILITY_BY_LABEL[product["volatility"]]
    droplet = product["required_droplet_class"]
    if droplet in {item.value for item in DropletSize}:
        st.session_state.droplet = droplet


def apply_sensor_mode() -> None:
    allowed = (
        THREE_SENSOR_SCENARIOS
        if st.session_state.sensor_mode == THREE_SENSOR_MODE
        else SCENARIOS
    )
    allowed_names = {scenario.name for scenario in allowed}
    if st.session_state.get("preset") not in allowed_names:
        st.session_state.preset = allowed[0].name
    apply_preset()


st.session_state.setdefault("sensor_mode", TWO_SENSOR_MODE)
st.session_state.setdefault("preset", SCENARIOS[0].name)
if "product_name" not in st.session_state:
    st.session_state.product_name = PRODUCTS[0]["name"]
    apply_catalog_product()
for field, default in next(iter(PRESETS.values())).items():
    st.session_state.setdefault(field, default)

st.markdown(
    """
    <style>
        .block-container {padding-top: 2rem; padding-bottom: 3rem;}
        [data-testid="stSidebar"] {border-right: 1px solid rgba(128,128,128,.2);}
        .eyebrow {font-size: .78rem; font-weight: 700; letter-spacing: .12em;
                  text-transform: uppercase; opacity: .68; margin-bottom: .3rem;}
        .status-card {border-radius: 16px; padding: 1.35rem 1.5rem; color: white;
                     margin: .5rem 0 1.25rem 0;}
        .status-go {background: linear-gradient(120deg, #177245, #2f9665);}
        .status-caution {background: linear-gradient(120deg, #a05a00, #cf8620);}
        .status-stop {background: linear-gradient(120deg, #9f2d2d, #d04747);}
        .status-window {background: linear-gradient(120deg, #0e4d6c, #1d7a92);}
        .status-window .status-label {font-size: 1.45rem;}
        .status-label {font-size: 2.1rem; font-weight: 800; line-height: 1.1;}
        .status-note {font-size: .95rem; margin-top: .45rem; opacity: .95;}
        .disclaimer {font-size: .82rem; opacity: .7;}
    </style>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.markdown("## Current assessment")
    st.radio(
        "Sensor configuration",
        [TWO_SENSOR_MODE, THREE_SENSOR_MODE],
        key="sensor_mode",
        on_change=apply_sensor_mode,
        help="Compare the outer sensors or inspect both atmospheric layers.",
    )
    available_scenarios = (
        THREE_SENSOR_SCENARIOS
        if st.session_state.sensor_mode == THREE_SENSOR_MODE
        else SCENARIOS
    )
    st.selectbox(
        "Simulation scenario",
        [scenario.name for scenario in available_scenarios],
        key="preset",
        on_change=apply_preset,
        help="Choose a scenario, then adjust any reading manually.",
    )
    selected_scenario = SCENARIO_BY_NAME[st.session_state.preset]
    st.caption(
        f"{selected_scenario.description}  \n"
        f"Simulated at {selected_scenario.timestamp}"
    )

    st.markdown(f"### {st.session_state.lower_height:g} ft sensor")
    lower_a, lower_b = st.columns(2)
    lower_a.number_input(
        "Temperature (°F)",
        min_value=-20.0,
        max_value=140.0,
        step=0.5,
        key="lower_temp",
    )
    lower_b.number_input(
        "Wind (mph)",
        min_value=0.0,
        max_value=50.0,
        step=0.5,
        key="lower_wind",
    )
    st.slider("Wind direction (°)", 0, 359, key="lower_direction")

    if st.session_state.sensor_mode == THREE_SENSOR_MODE:
        st.markdown(f"### {st.session_state.middle_height:g} ft sensor")
        middle_a, middle_b = st.columns(2)
        middle_a.number_input(
            "Temperature (°F) · middle",
            min_value=-20.0,
            max_value=140.0,
            step=0.5,
            key="middle_temp",
        )
        middle_b.number_input(
            "Wind (mph) · middle",
            min_value=0.0,
            max_value=50.0,
            step=0.5,
            key="middle_wind",
        )
        st.slider(
            "Wind direction (°) · middle",
            0,
            359,
            key="middle_direction",
        )

    st.markdown(f"### {st.session_state.upper_height:g} ft sensor")
    upper_a, upper_b = st.columns(2)
    upper_a.number_input(
        "Temperature (°F) ",
        min_value=-20.0,
        max_value=140.0,
        step=0.5,
        key="upper_temp",
    )
    upper_b.number_input(
        "Wind (mph) ",
        min_value=0.0,
        max_value=50.0,
        step=0.5,
        key="upper_wind",
    )
    st.slider("Wind direction (°) ", 0, 359, key="upper_direction")

    st.markdown("### Application")
    st.selectbox(
        "Product",
        list(PRODUCT_BY_NAME),
        key="product_name",
        on_change=apply_catalog_product,
        help="Label wind and temperature limits come from the selected product.",
    )
    volatility_value = st.selectbox(
        "Volatility",
        [item.value for item in Volatility],
        key="volatility",
        help="Use the product label and SDS to select the closest category.",
    )
    droplet_value = st.selectbox(
        "Droplet size",
        [item.value for item in DropletSize],
        key="droplet",
        help="Fine droplets are more prone to physical drift.",
    )

reading = WeatherReading(
    lower_temp_f=st.session_state.lower_temp,
    upper_temp_f=st.session_state.upper_temp,
    lower_wind_mph=st.session_state.lower_wind,
    upper_wind_mph=st.session_state.upper_wind,
    lower_direction_deg=st.session_state.lower_direction,
    upper_direction_deg=st.session_state.upper_direction,
    lower_height_ft=st.session_state.lower_height,
    upper_height_ft=st.session_state.upper_height,
)
application = ApplicationSettings(
    product_name=st.session_state.product_name,
    volatility=Volatility(volatility_value),
    droplet_size=DropletSize(droplet_value),
)
selected_product = PRODUCT_BY_NAME[st.session_state.product_name]
spray_limits = limits_for_product(selected_product, SITE)
spray_windows = predict_spray_windows(spray_limits)
go_moment = datetime.fromisoformat(selected_scenario.timestamp)
next_window_alert = alert_for_go(spray_windows, go_moment)
display_readings = [
    SensorReading(
        height_ft=reading.lower_height_ft,
        temperature_f=reading.lower_temp_f,
        wind_speed_mph=reading.lower_wind_mph,
        wind_direction_deg=reading.lower_direction_deg,
    )
]
if st.session_state.sensor_mode == THREE_SENSOR_MODE:
    display_readings.append(
        SensorReading(
            height_ft=st.session_state.middle_height,
            temperature_f=st.session_state.middle_temp,
            wind_speed_mph=st.session_state.middle_wind,
            wind_direction_deg=st.session_state.middle_direction,
        )
    )
display_readings.append(
    SensorReading(
        height_ft=reading.upper_height_ft,
        temperature_f=reading.upper_temp_f,
        wind_speed_mph=reading.upper_wind_mph,
        wind_direction_deg=reading.upper_direction_deg,
    )
)
assessment = (
    assess_multi_height_risk(display_readings, application)
    if st.session_state.sensor_mode == THREE_SENSOR_MODE
    else assess_spray_risk(reading, application)
)

with st.sidebar:
    if st.button("Save assessment", type="primary", width="stretch"):
        st.session_state.last_saved = save_assessment(
            reading,
            application,
            assessment,
            sensor_readings=display_readings,
        )
    if "last_saved" in st.session_state:
        saved_time = datetime.fromisoformat(st.session_state.last_saved)
        st.caption(f"Last saved: {saved_time:%Y-%m-%d %H:%M:%S} UTC")

st.markdown('<div class="eyebrow">Orchard weather intelligence</div>', unsafe_allow_html=True)
st.title("Orchard Drift Guard")
st.caption(
    f"{st.session_state.sensor_mode} · vertical weather checks for clearer spray decisions."
)

current_tab, windows_tab, history_tab, method_tab = st.tabs(
    ["Live decision", "Spray windows", "Assessment log", "How it works"]
)

with current_tab:
    if st.session_state.sensor_mode == THREE_SENSOR_MODE:
        st.info(
            "Three-sensor mode evaluates the 5–15 ft and 15–30 ft layers "
            "separately, revealing changes that an endpoint-only comparison can miss."
        )
    status_class = assessment.status.name.lower()
    st.markdown(
        f"""
        <div class="status-card status-{status_class}">
            <div class="eyebrow">Current recommendation</div>
            <div class="status-label">{STATUS_LABEL[assessment.status]}</div>
            <div class="status-note">{assessment.recommendation}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    if assessment.status == Status.GO:
        upcoming = next_window_alert.next_window
        start_by = (
            latest_start(upcoming, spray_limits.minimum_window) if upcoming else None
        )
        headline = (
            f"{format_clock(start_by)} {start_by:%a}" if start_by else "No later window"
        )
        st.markdown(
            f"""
            <div class="status-card status-window">
                <div class="eyebrow">Next window · start by</div>
                <div class="status-label">{headline}</div>
                <div class="status-note">{next_window_alert.message}</div>
                <div class="status-note">Push · {next_window_alert.push or "No later window."}</div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    st.markdown("#### What the sensors see")
    sensor_columns = st.columns(len(display_readings))
    for column, sensor in zip(sensor_columns, display_readings):
        column.metric(
            f"{sensor.height_ft:g} ft · temperature",
            f"{sensor.temperature_f:.1f} °F",
            f"{sensor.wind_speed_mph:.1f} mph · {sensor.wind_direction_deg:.0f}°",
            delta_color="off",
        )

    inversion, shear = st.columns(2)
    inversion.metric(
        "Largest adjacent temperature change",
        f"{assessment.inversion_delta_f:+.1f} °F",
        "inversion" if assessment.inversion_delta_f > 0 else "normal profile",
        delta_color="inverse",
    )
    shear.metric(
        "Largest adjacent wind shear",
        f"{assessment.wind_speed_delta_mph:.1f} mph",
        f"{assessment.wind_direction_delta_deg:.0f}° direction shift",
        delta_color="off",
    )

    st.markdown("#### Why")
    if not assessment.alerts:
        st.success(
            "No inversion, out-of-range wind, or significant wind shear was "
            "detected at the configured thresholds."
        )
    for alert in assessment.alerts:
        message = f"**{alert.title}.** {alert.explanation}"
        if alert.status.name == "STOP":
            st.error(message)
        else:
            st.warning(message)

    st.markdown(
        '<p class="disclaimer">Decision support only. Always follow the pesticide '
        "label, regulations, permit conditions, buffer zones, and on-site checks. "
        "No tool can guarantee zero drift.</p>",
        unsafe_allow_html=True,
    )

with windows_tab:
    minimum_hours = spray_limits.minimum_window.total_seconds() / 3600
    st.caption(
        f"Label · {selected_product['name']}: wind "
        f"{spray_limits.min_wind_mph:g}–{spray_limits.max_wind_mph:g} mph, "
        f"temperature at or below {spray_limits.max_temp_f:g}°F, "
        f"rain under {spray_limits.max_precip_probability:g}%."
    )
    st.caption(
        "Settings · spray hours "
        f"{format_clock(spray_limits.spray_start)}–{format_clock(spray_limits.spray_end)}, "
        f"minimum window {minimum_hours:g} hours. "
        "Monday–Friday is common, Saturday is possible, and Sunday is less common. "
        "A tower hour has to be Go. A forecast hour leaves inversion unseen."
    )
    if selected_product["volatility"] == "high":
        st.caption(
            "This product is high volatility, so a clear weather window still "
            "reads Caution on the live decision."
        )

    st.markdown("#### Planned sprays")
    planned = [job for job in load_spray_jobs() if job.status == "planned"]
    if planned:
        for job in planned:
            if job.earliest_start is None or job.latest_end is None:
                continue
            product = PRODUCT_BY_ID[job.product_id]
            job_limits = limits_for_product(product, SITE)
            fit = first_fitting_window(
                predict_spray_windows(job_limits),
                job.earliest_start,
                job.latest_end,
                job.duration,
            )
            title = (
                f"**{job.application_id} · {job.block_id} · {product['name']}**"
            )
            if fit is None:
                st.warning(
                    f"{title}  \nNo window inside "
                    f"{job.earliest_start:%a} {format_clock(job.earliest_start)}–"
                    f"{format_clock(job.latest_end)}."
                )
                continue
            start_by = latest_start(
                fit, job.duration, job.earliest_start, job.latest_end
            )
            usable_start = max(fit.start, job.earliest_start)
            usable_end = min(fit.end, job.latest_end)
            why = planned_why(fit, job.earliest_start, job.latest_end)
            push = push_text(
                fit,
                job.duration,
                f"{job.application_id} {job.block_id}",
                job.earliest_start,
                job.latest_end,
            )
            start_by_text = (
                f"{format_clock(start_by)} {start_by:%A}" if start_by else "No start"
            )
            usable = (
                f"{usable_start:%a} {format_clock(usable_start)}–"
                f"{format_clock(usable_end)}"
            )
            st.markdown(f"{title}  \nStart by {start_by_text}")
            detail = (
                f"{usable} · {fit.likelihood} · {confidence_marker(fit)}"
            )
            if why:
                detail = f"{detail}. {why}."
            st.caption(detail)
            st.caption(f"Push · {push}")
    else:
        st.info("No planned sprays are on the schedule.")

    st.markdown("#### All windows")
    st.caption("Start by here is for the 2-hour setting.")
    if spray_windows:
        for window in spray_windows:
            start_by = latest_start(window, spray_limits.minimum_window)
            start_by_text = format_clock(start_by) if start_by else "No start"
            why = window_why(window)
            reason = f" {why}." if why else ""
            st.markdown(
                f"**{format_window_span(window)}** · {window.likelihood} · "
                f"{confidence_marker(window)}  \n"
                f"Start by {start_by_text}.{reason}"
            )
    else:
        st.info("No spray window in this forecast for the selected product.")

with history_tab:
    history_header, history_filter = st.columns([3, 1])
    history_header.markdown("#### Time-stamped assessment log")
    selected_status = history_filter.selectbox(
        "Filter status", list(STATUS_FILTER)
    )
    records = get_assessments(STATUS_FILTER[selected_status])

    if records:
        display_records = []
        for record in records:
            reasons = json.loads(record["reasons"])
            profile = (
                json.loads(record["sensor_profile"])
                if record.get("sensor_profile")
                else []
            )
            display_records.append(
                {
                    "UTC time": record["recorded_at"].replace("T", " "),
                    "Status": STATUS_LABEL.get(Status[record["status"]], record["status"]),
                    "5 ft temp": f'{record["lower_temp_f"]:.1f} °F',
                    "30 ft temp": f'{record["upper_temp_f"]:.1f} °F',
                    "5 ft wind": f'{record["lower_wind_mph"]:.1f} mph',
                    "30 ft wind": f'{record["upper_wind_mph"]:.1f} mph',
                    "Product": record["product_name"],
                    "Sensor profile": " · ".join(
                        f'{sensor["height_ft"]:g} ft: '
                        f'{sensor["temperature_f"]:.1f} °F, '
                        f'{sensor["wind_speed_mph"]:.1f} mph'
                        for sensor in profile
                    )
                    or "Legacy outer-sensor record",
                    "Triggers": " | ".join(reasons) or "None",
                }
            )
        st.dataframe(display_records, width="stretch", hide_index=True)
        st.download_button(
            "Download filtered log as CSV",
            assessments_to_csv(records),
            file_name="orchard-drift-assessments.csv",
            mime="text/csv",
        )
    else:
        st.info("No saved assessments match this filter.")

with method_tab:
    st.markdown(
        """
        #### Decision rules
        - **Stop — inversion:** an upper sensor is warmer than the sensor immediately
          below it.
        - **Stop — wind band:** wind at any measured height is below 3 mph or above
          10 mph.
        - **Caution — speed shear:** any two sensor wind speeds differ by 5 mph
          or more.
        - **Caution — direction shear:** any two wind directions differ by 45°
          or more.
        - **Application modifier:** high volatility or fine droplets raise a Go or
          Caution result by one level.
        - **Next spray window:** a Go names the next window and the latest start
          for a 2-hour job. Label limits are wind, temperature, and rain. Settings
          are spray hours 4 AM–10 PM and a 2-hour minimum. Monday–Friday is common,
          Saturday is possible, and Sunday is less common. Tower hours have to be
          Go. Forecast hours leave inversion unseen. The push line is the short
          ntfy text.

        The two-sensor view evaluates one 5–30 ft layer. The three-sensor view
        evaluates 5–15 ft and 15–30 ft independently, so it can locate a shallow
        inversion or wind shift instead of averaging over the whole profile.

        Direction shear uses the shortest circular difference, so 350° and 10° are
        correctly treated as 20° apart. Thresholds are demonstration defaults and must
        be replaced by product-label and local requirements for operational use.
        """
    )
