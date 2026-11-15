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
    Volatility,
    WeatherReading,
)
from driftguard.risk import assess_multi_height_risk, assess_spray_risk
from driftguard.storage import (
    assessments_to_csv,
    create_notification,
    get_assessments,
    get_notifications,
    mark_all_notifications_read,
    save_assessment,
)

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
st.session_state.setdefault("spray_active", False)
st.session_state.setdefault("spray_started_at", None)
st.session_state.setdefault("last_spray_status", None)
st.session_state.setdefault("auto_stop_notice", None)
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
    product_name = st.text_input("Product", "Unspecified product")
    volatility_value = st.selectbox(
        "Volatility",
        [item.value for item in Volatility],
        index=1,
        help="Use the product label and SDS to select the closest category.",
    )
    droplet_value = st.selectbox(
        "Droplet size",
        [item.value for item in DropletSize],
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
    product_name=product_name.strip() or "Unspecified product",
    volatility=Volatility(volatility_value),
    droplet_size=DropletSize(droplet_value),
)
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

current_status = assessment.status.name
if (
    st.session_state.spray_active
    and st.session_state.last_spray_status
    and current_status != st.session_state.last_spray_status
):
    if current_status == "STOP":
        notification_level = "error"
        notification_title = "Spraying automatically stopped"
        notification_message = (
            f"The dashboard ended the active spray session for "
            f"{application.product_name} because conditions changed to STOP. "
            "Confirm that the physical sprayer has been shut off."
        )
        event_type = "spray_auto_stopped"
    elif current_status == "GO":
        notification_level = "success"
        notification_title = "Conditions returned to GO"
        notification_message = (
            "Weather conditions are back within the configured limits. "
            "Reconfirm the label and site before continuing."
        )
        event_type = "condition_changed"
    else:
        notification_level = "warning"
        notification_title = f"Active spray changed to {current_status}"
        notification_message = (
            f"Conditions changed while spraying {application.product_name}. "
            f"Current recommendation: {current_status}. {assessment.recommendation}"
        )
        event_type = "condition_changed"
    create_notification(
        notification_title,
        notification_message,
        notification_level,
        event_type,
    )
    st.toast(notification_title, icon="🔔")
    if current_status == "STOP":
        st.session_state.spray_active = False
        st.session_state.spray_started_at = None
        st.session_state.last_spray_status = None
        st.session_state.auto_stop_notice = notification_message
    else:
        st.session_state.last_spray_status = current_status

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

notifications = get_notifications()
unread_count = sum(not item["is_read"] for item in notifications)
current_tab, notification_tab, history_tab, method_tab = st.tabs(
    [
        "Live decision",
        f"Notifications ({unread_count})",
        "Assessment log",
        "How it works",
    ]
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
            <div class="status-label">{assessment.status.name}</div>
            <div class="status-note">{assessment.recommendation}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown("#### Spray activity")
    if st.session_state.auto_stop_notice:
        st.error(
            f"**Automatic software stop:** {st.session_state.auto_stop_notice}"
        )
        if st.button("Acknowledge automatic stop"):
            st.session_state.auto_stop_notice = None
            st.rerun()

    if st.session_state.spray_active:
        activity_message = (
            f"**Spraying in progress:** {application.product_name}  \n"
            f"Started {st.session_state.spray_started_at}"
        )
        if current_status == "GO":
            st.success(activity_message)
        else:
            st.error(
                f"{activity_message}  \n"
                f"Current recommendation is **{current_status}**. Follow the label "
                "and stop the application when required."
            )
        if st.button("Stop spraying", type="primary"):
            stopped_at = create_notification(
                "Spraying stopped",
                f"The applicator stopped spraying {application.product_name}.",
                "info",
                "spray_stopped",
            )
            st.session_state.spray_active = False
            st.session_state.spray_started_at = None
            st.session_state.last_spray_status = None
            st.toast("Spraying stopped", icon="⏹️")
            st.session_state.last_notification_at = stopped_at
            st.rerun()
    else:
        start_disabled = current_status != "GO"
        if st.button(
            "Start spraying & notify",
            type="primary",
            disabled=start_disabled,
        ):
            started_at = create_notification(
                "Pesticide spraying started",
                (
                    f"{application.product_name} is being sprayed under a GO "
                    f"assessment using {st.session_state.sensor_mode}."
                ),
                "success",
                "spray_started",
            )
            st.session_state.last_saved = save_assessment(
                reading,
                application,
                assessment,
                sensor_readings=display_readings,
            )
            st.session_state.spray_active = True
            st.session_state.spray_started_at = started_at
            st.session_state.last_spray_status = current_status
            st.session_state.auto_stop_notice = None
            st.toast("Pesticide spraying started", icon="📣")
            st.rerun()
        if start_disabled:
            st.caption(
                "Starting is disabled because the current recommendation is not GO."
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

with notification_tab:
    notification_header, notification_action = st.columns([3, 1])
    notification_header.markdown("#### In-app notification history")
    if unread_count and notification_action.button(
        "Mark all as read", width="stretch"
    ):
        mark_all_notifications_read()
        st.rerun()

    if notifications:
        for notification in notifications:
            unread_label = " · NEW" if not notification["is_read"] else ""
            message = (
                f'**{notification["title"]}{unread_label}**  \n'
                f'{notification["message"]}  \n'
                f'`{notification["created_at"]}`'
            )
            getattr(st, notification["level"])(message)
    else:
        st.info(
            "No notifications yet. A GO assessment enables the Start spraying action."
        )

with history_tab:
    history_header, history_filter = st.columns([3, 1])
    history_header.markdown("#### Time-stamped assessment log")
    selected_status = history_filter.selectbox(
        "Filter status", ["All", "GO", "CAUTION", "STOP"]
    )
    records = get_assessments(selected_status)

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
                    "Status": record["status"],
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
        - **STOP — inversion:** an upper sensor is warmer than the sensor immediately
          below it.
        - **STOP — wind band:** wind at any measured height is below 3 mph or above
          10 mph.
        - **CAUTION — speed shear:** any two sensor wind speeds differ by 5 mph
          or more.
        - **CAUTION — direction shear:** any two wind directions differ by 45°
          or more.
        - **Application modifier:** high volatility or fine droplets raise a GO or
          CAUTION result by one level.

        The two-sensor view evaluates one 5–30 ft layer. The three-sensor view
        evaluates 5–15 ft and 15–30 ft independently, so it can locate a shallow
        inversion or wind shift instead of averaging over the whole profile.

        Direction shear uses the shortest circular difference, so 350° and 10° are
        correctly treated as 20° apart. Thresholds are demonstration defaults and must
        be replaced by product-label and local requirements for operational use.

        #### Notifications
        GO means conditions passed the configured checks; it does not mean spraying
        automatically began. The applicator must choose **Start spraying & notify**.
        The app then records the event, shows an active-spray banner, and creates
        another alert if conditions change to CAUTION. A STOP result automatically
        ends the active software session and requires acknowledgement. Physical
        equipment still needs a connected hardware interlock to shut off automatically.
        """
    )
