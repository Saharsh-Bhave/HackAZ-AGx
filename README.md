# Orchard Drift Guard

Orchard Drift Guard is a Streamlit decision-support dashboard for reducing
pesticide drift in tree orchards. It combines temperature and wind readings from
multiple heights to detect conditions that can look safe at ground level but
create drift risk above or inside the canopy.

The dashboard produces an explainable *GO, **CAUTION, or **STOP*
recommendation. It supports simulated scenarios, time-series sensor playback,
automatic assessment logging, spray-state notifications, and advisory forecast
windows.

> This prototype supports an applicator's decision. It does not replace the
> pesticide label, regulations, permits, on-site observations, buffer zones, or
> professional judgment.

## Features

### Two- and three-sensor comparison

- *Two sensors:* compares readings at 5 ft and 30 ft.
- *Three sensors:* evaluates readings at 5 ft, 15 ft, and 30 ft.
- Three-sensor mode checks the 5–15 ft and 15–30 ft temperature layers
  independently, which can reveal a shallow inversion hidden by an endpoint-only
  comparison.
- Wind limits are checked at every measured height.
- Wind shear uses the largest speed and direction difference among the sensors.

### Explainable risk decisions

- *STOP — inversion:* an upper sensor is warmer than the sensor immediately
  below it.
- *STOP — low wind:* wind at any measured height is below 3 mph.
- *STOP — high wind:* wind at any measured height is above 10 mph.
- *CAUTION — speed shear:* sensor wind speeds differ by at least 5 mph.
- *CAUTION — direction shear:* wind directions differ by at least 45 degrees.
- High product volatility or fine droplets raise a GO or CAUTION result by one
  severity level.
- Every alert includes the measured values and a plain-language explanation.

Direction shear uses the shortest circular difference, so 350 degrees and
10 degrees are correctly treated as 20 degrees apart.

### Data sources

The *Data source* control supports:

1. *Scenario snapshots*
   - Loads curated examples from data/scenarios.json.
   - Includes safe conditions, hidden inversions, calm wind, high wind above the
     canopy, wind shear, boundary values, and sensor-quality examples.
   - Sensor values can be adjusted manually during a demonstration.

2. *Live timeline playback*
   - Replays data/tower_readings.csv as a simulated live sensor feed.
   - Groups 5 ft, 15 ft, and 30 ft readings by their original timestamp.
   - Supports a timeline slider, previous/next controls, automatic playback, and
     1-, 2-, or 5-second playback intervals.
   - Each timestamp is assessed and logged automatically.
   - Only complete, good-quality profiles required by the selected sensor mode
     are included.

Physical live-sensor ingestion through MQTT or HTTP is future work.

### Spray workflow and notifications

- A new GO condition creates a *GO conditions available* notification.
- GO enables the *Start Spraying* button; spraying never starts automatically.
- Starting creates a persistent notification and an active-spray banner.
- A transition to CAUTION while spraying creates a warning.
- A transition to STOP automatically ends the dashboard's active software
  session and creates a high-priority notification.
- The automatic software stop must be acknowledged.
- Notifications are persisted in SQLite and displayed in notification history.
- Notifications can be marked as read.

The software cannot physically stop a pump or valve without a connected hardware
interlock.

### Automatic assessment log

Each new sensor profile or application-setting change is saved with:

- Original sensor observation time
- Database logging time
- GO, CAUTION, or STOP status
- Sensor readings and heights
- Product, volatility, and droplet settings
- Triggered alerts and explanations

GO records display *No risk triggers*. Records can be filtered by status and
exported as CSV.

### Candidate spray windows

The *Spray windows* tab analyzes the simulated hourly NWS forecast in
data/nws_forecast_hourly.json.

A candidate window requires:

- Daytime forecast hours
- Wind of at least 3 mph
- Wind no higher than the application limit
- Temperature no higher than the application limit
- Precipitation probability of 20% or less
- Enough contiguous hours for the selected application duration

High-volatility applications use stricter demonstration limits of 8 mph and
80°F. Each candidate displays its duration, wind range, temperature range,
precipitation probability, and confidence.

Every new STOP alert is followed by another notification containing the next
candidate spray window. If none is available, the notification says that no
qualifying window remains in the forecast. Forecast windows are advisory—not GO decisions. Regional forecasts do not
contain a future vertical temperature profile and therefore cannot confirm an
orchard inversion. Current multi-height readings must be checked before and
during spraying.

## Run locally

Python 3.11 or newer is recommended.

bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py

Open the URL printed by Streamlit, normally
http://localhost:8501.

## Dashboard tabs

- *Live decision:* current status, spray controls, sensor readings, and reasons.
- *Spray windows:* upcoming advisory forecast windows.
- *Notifications:* GO, spray-start, condition-change, automatic-stop, and
  next-window messages.
- *Assessment log:* automatic reading history, filters, and CSV export.
- *How it works:* decision rules and limitations.

## Project structure
- app.py — Streamlit dashboard and user workflow.
- driftguard/models.py — shared weather, application, alert, and result models.
- driftguard/data.py — scenario and tower-timeline loaders.
- driftguard/risk.py — two- and multi-height risk engines.
- driftguard/forecast.py — hourly forecast parsing and candidate-window logic.
- driftguard/storage.py — SQLite assessments and notifications.
- tests/ — risk, data, forecast, storage, and notification tests.
- data/ — simulated tower, station, forecast, product, application, and site
  datasets.

## Tests

bash
pytest


The suite covers inversion detection, wind boundaries, circular direction
differences, two- versus three-sensor behavior, timeline loading, candidate
forecast windows, persistence, and notifications.

## Scope and limitations
- Thresholds are demonstration defaults; actual limits come from the product
  label and local requirements.
- Forecast weather is regional and may not match conditions inside an orchard.
- Sensor placement, calibration, freshness, and quality affect the result.
- Conditions can vary within a single orchard block.
- Simulated playback is not a physical live feed.
- No software system can guarantee zero pesticide drift.
