# Orchard Drift Guard

Orchard Drift Guard is a decision-support dashboard that compares temperature
and wind at 5 ft and 30 ft before a pesticide application. It detects
temperature inversions, unsafe wind speeds, and vertical wind shear, then gives
an explainable **GO**, **CAUTION**, or **STOP** recommendation.

The MVP loads the multi-height snapshots in `data/scenarios.json` and also
accepts manually adjusted readings. It uses the lowest and highest valid sensor
heights in each scenario. Every saved assessment is time-stamped in a local
SQLite log and can be exported as CSV.

## Run locally

Python 3.11 or newer is recommended.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

Open the local URL printed by Streamlit. Select a demonstration scenario or
adjust either sensor manually. The decision updates live; choose **Save
assessment** to add it to the audit log.

## Decision rules

| Condition | Default result |
| --- | --- |
| 30 ft temperature is warmer than 5 ft | STOP |
| Wind at either height is below 3 mph or above 10 mph | STOP |
| Wind speeds differ by at least 5 mph | CAUTION |
| Wind directions differ by at least 45° | CAUTION |
| High volatility or fine droplets | Raise one level |

These are configurable demonstration thresholds, not universal legal limits.
Product-label directions and local rules always take precedence.

## Tests

```bash
pytest
```

## Scope and limitations

This tool supports, but does not replace, pesticide labels, on-site observations,
regulations, permit conditions, buffer zones, or professional judgment. Sensor
placement and calibration matter, weather can vary within a block, and no
system can guarantee zero drift.