"""Generate the simulated dataset for the Spray or Wait? decision-support tool.

Run:  python3 generate_data.py

Everything is written to ./data and is fully reproducible (fixed seed).
All sites, people, products and readings are fictional.

Files
  tower_readings.csv        On-site tower, 3 heights (5/15/30 ft), every 5 min, Nov 11-14.
                            One row per sensor per timestamp.
  ground_station.csv        Single-height regional station (6.5 ft), every 15 min, Nov 11-14.
                            This is the "ground station says it looks fine" comparison.
  nws_forecast_hourly.json  Hourly regional forecast, Nov 11-16, shaped like the
                            api.weather.gov hourly forecast response.
  products.json             Fictional pesticide products with volatility and label limits.
  applications.csv          Completed and planned spray applications.
  site.json                 Orchard, tower, blocks, sensitive areas, alert contacts.
  scenarios.json            Hand-built single snapshots for demo buttons and unit tests.
  timeline_annotations.csv  What is happening in the time series, and when.
                            ground_station_looks_ok is yes / no / mixed / n/a: whether the
                            single-height station's wind stays inside 3-10 mph in that window.

Conventions
  Times are local Pacific Standard Time with a -08:00 offset.
  Wind direction is the direction the wind blows FROM, in degrees (0 = N, 90 = E).
  Spray drifts toward (direction + 180) % 360.
"""

import csv
import json
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

SEED = 20261111
TZ = timezone(timedelta(hours=-8))
START = datetime(2026, 11, 11, tzinfo=TZ)
STEP_MIN = 5
STEPS_PER_HOUR = 60 // STEP_MIN
TOWER_DAYS = 4       # tower and ground station history
MODEL_DAYS = 6       # the forecast runs two days past the history
SUNRISE_H, SUNSET_H = 6.58, 16.83
OUT = Path(__file__).parent / "data"

HEIGHTS = (5, 15, 30)
# How far each sensor sits between the 5 ft and 30 ft values.
TEMP_FRAC = {5: 0.0, 15: 0.45, 30: 1.0}
WIND_FRAC = {5: 0.0, 15: 0.42, 30: 1.0}
DIR_FRAC = {5: 1.0, 15: 0.45, 30: 0.0}

# ---------------------------------------------------------------------------
# The weather story, as "day HH:MM" control points that are interpolated.
# Day 1 = Nov 11. Days 5-6 exist only to drive the forecast.
# ---------------------------------------------------------------------------
KNOTS = {
    # Temperature at 5 ft (F)
    "t5": [
        ("1 00:00", 47.0), ("1 03:00", 44.5), ("1 06:30", 42.5), ("1 08:00", 45.0),
        ("1 10:00", 54.0), ("1 12:00", 61.5), ("1 14:30", 66.0), ("1 16:00", 64.0),
        ("1 17:00", 59.0), ("1 19:00", 53.5), ("1 22:00", 49.5),
        ("2 00:00", 48.0), ("2 03:00", 46.5), ("2 06:45", 45.5), ("2 08:00", 47.5),
        ("2 10:00", 56.0), ("2 12:00", 63.0), ("2 14:30", 67.5), ("2 16:00", 65.5),
        ("2 17:00", 60.0), ("2 19:00", 55.0), ("2 22:00", 53.0),
        ("3 00:00", 52.5), ("3 03:00", 52.0), ("3 06:30", 51.0), ("3 09:00", 53.5),
        ("3 12:00", 58.5), ("3 13:30", 60.0), ("3 15:00", 56.0), ("3 17:00", 53.0),
        ("3 20:00", 49.0), ("3 23:00", 45.0),
        ("4 00:00", 44.0), ("4 03:00", 41.0), ("4 06:40", 38.0), ("4 08:00", 40.5),
        ("4 10:00", 49.0), ("4 12:00", 56.5), ("4 14:30", 61.0), ("4 16:00", 59.0),
        ("4 17:00", 54.0), ("4 19:00", 48.5), ("4 22:00", 45.0),
        ("5 00:00", 43.5), ("5 06:40", 39.5), ("5 10:00", 51.0), ("5 14:30", 63.0),
        ("5 17:00", 56.0), ("5 22:00", 48.0),
        ("6 00:00", 47.0), ("6 06:40", 44.0), ("6 10:00", 54.0), ("6 14:30", 64.0),
        ("6 17:00", 59.0), ("6 22:00", 54.0), ("7 00:00", 53.0),
    ],
    # Temperature at 30 ft minus temperature at 5 ft (F). Positive = inversion.
    "dt": [
        ("1 00:00", 5.0), ("1 06:30", 6.5), ("1 07:30", 5.5), ("1 08:30", 1.5),
        ("1 09:00", -0.3), ("1 10:00", -1.2), ("1 14:00", -1.8), ("1 15:30", -0.8),
        ("1 16:15", 0.3), ("1 17:00", 2.0), ("1 19:00", 4.0), ("1 23:00", 4.5),
        ("2 00:00", 4.5), ("2 05:00", 4.5), ("2 06:45", 5.0), ("2 08:00", 4.2),
        ("2 08:45", 2.0), ("2 09:30", -0.3), ("2 10:30", -1.2), ("2 14:00", -1.6),
        ("2 15:45", -0.6), ("2 16:20", 0.4), ("2 17:00", 2.2), ("2 19:00", 3.6),
        ("2 21:00", 2.5), ("2 23:00", 0.8),
        ("3 00:30", -0.2), ("3 06:00", -0.3), ("3 09:00", -0.6), ("3 12:00", -1.0),
        ("3 15:00", -0.6), ("3 18:00", -0.3), ("3 20:00", 0.5), ("3 22:00", 2.0),
        ("4 00:00", 3.0), ("4 06:40", 4.5), ("4 08:00", 3.5), ("4 09:15", 0.2),
        ("4 09:45", -0.5), ("4 11:00", -1.3), ("4 14:00", -1.8), ("4 15:30", -0.8),
        ("4 16:10", 0.3), ("4 17:00", 2.2), ("4 20:00", 4.5),
        ("5 00:00", 5.0), ("5 06:40", 6.0), ("5 09:00", 0.0), ("5 10:00", -1.2),
        ("5 14:00", -1.8), ("5 16:15", 0.3), ("5 19:00", 3.5),
        ("6 00:00", 3.0), ("6 06:40", 3.0), ("6 08:30", 0.0), ("6 10:00", -1.0),
        ("6 14:00", -1.2), ("6 16:30", 0.0), ("6 20:00", 0.8), ("7 00:00", 0.3),
    ],
    # Wind speed at 30 ft (mph)
    "u30": [
        ("1 00:00", 3.5), ("1 05:00", 3.0), ("1 08:00", 3.5), ("1 09:30", 5.2),
        ("1 11:00", 7.2), ("1 14:00", 8.0), ("1 16:00", 6.2), ("1 17:30", 4.0),
        ("1 21:00", 3.5),
        ("2 00:00", 4.0), ("2 03:00", 6.0), ("2 05:00", 8.6), ("2 07:00", 9.0),
        ("2 08:45", 8.6), ("2 10:00", 7.0), ("2 12:00", 7.4), ("2 14:30", 7.6),
        ("2 16:00", 6.0), ("2 17:30", 4.5), ("2 21:00", 5.5),
        ("3 00:00", 7.0), ("3 04:00", 7.4), ("3 08:00", 7.6), ("3 09:30", 8.2),
        ("3 10:15", 10.8), ("3 11:00", 13.0), ("3 12:30", 17.0), ("3 14:00", 19.0),
        ("3 15:00", 16.0), ("3 17:00", 11.0), ("3 19:00", 7.5), ("3 22:00", 5.0),
        ("4 00:00", 4.0), ("4 04:00", 3.0), ("4 08:00", 3.0), ("4 10:00", 3.2),
        ("4 11:30", 3.8), ("4 12:15", 5.8), ("4 14:00", 6.6), ("4 15:45", 6.0),
        ("4 17:30", 3.5), ("4 21:00", 3.0),
        ("5 00:00", 3.0), ("5 08:00", 3.0), ("5 10:30", 5.5), ("5 14:00", 7.5),
        ("5 16:30", 5.5), ("5 18:00", 3.5),
        ("6 00:00", 4.0), ("6 06:00", 5.0), ("6 10:00", 8.0), ("6 14:00", 12.0),
        ("6 17:00", 11.0), ("6 21:00", 9.0), ("7 00:00", 8.0),
    ],
    # Wind speed at 5 ft (mph)
    "u5": [
        ("1 00:00", 1.2), ("1 05:00", 0.9), ("1 08:00", 1.3), ("1 09:30", 3.6),
        ("1 11:00", 5.4), ("1 14:00", 6.0), ("1 16:00", 4.5), ("1 17:30", 1.8),
        ("1 21:00", 1.3),
        ("2 00:00", 1.5), ("2 03:00", 2.6), ("2 05:00", 4.5), ("2 07:00", 4.8),
        ("2 08:45", 4.6), ("2 10:00", 5.0), ("2 12:00", 5.5), ("2 14:30", 5.7),
        ("2 16:00", 4.4), ("2 17:30", 2.0), ("2 21:00", 3.0),
        ("3 00:00", 5.0), ("3 04:00", 5.4), ("3 08:00", 5.6), ("3 09:30", 6.0),
        ("3 10:15", 6.8), ("3 11:00", 8.0), ("3 12:30", 11.5), ("3 14:00", 13.0),
        ("3 15:00", 11.0), ("3 17:00", 7.2), ("3 19:00", 4.8), ("3 22:00", 2.5),
        ("4 00:00", 1.6), ("4 04:00", 0.8), ("4 08:00", 0.9), ("4 10:00", 1.8),
        ("4 11:30", 2.4), ("4 12:15", 4.2), ("4 14:00", 4.9), ("4 15:45", 4.5),
        ("4 17:30", 1.5), ("4 21:00", 1.0),
        ("5 00:00", 1.0), ("5 08:00", 1.0), ("5 10:30", 4.0), ("5 14:00", 5.6),
        ("5 16:30", 4.0), ("5 18:00", 1.5),
        ("6 00:00", 1.8), ("6 06:00", 3.0), ("6 10:00", 5.8), ("6 14:00", 8.5),
        ("6 17:00", 7.8), ("6 21:00", 6.2), ("7 00:00", 5.5),
    ],
    # Wind direction at 30 ft (degrees, unwrapped so turns interpolate the right way)
    "d30": [
        ("1 00:00", 120), ("1 08:00", 130), ("1 10:00", 300), ("1 16:00", 320),
        ("1 18:30", 330), ("1 22:00", 490),
        ("2 00:00", 500), ("2 03:00", 530), ("2 05:00", 545), ("2 08:45", 545),
        ("2 10:30", 660), ("2 16:00", 680), ("2 18:30", 690), ("2 22:00", 860),
        ("3 00:00", 870), ("3 08:00", 880), ("3 12:30", 890), ("3 14:00", 900),
        ("3 14:45", 1020), ("3 17:00", 1040), ("3 22:00", 1050),
        ("4 00:00", 1050), ("4 04:00", 1180), ("4 08:00", 1190), ("4 10:00", 1210),
        ("4 12:15", 1390), ("4 14:00", 1400), ("4 17:30", 1410), ("4 21:00", 1550),
        ("5 00:00", 1560), ("5 08:00", 1570), ("5 10:30", 1740), ("5 16:30", 1760),
        ("5 18:00", 1770), ("5 22:00", 1930),
        ("6 00:00", 1940), ("6 06:00", 1950), ("6 14:00", 1960), ("6 21:00", 1965),
        ("7 00:00", 1970),
    ],
    # Wind direction at 5 ft minus direction at 30 ft (degrees)
    "dd": [
        ("1 00:00", -25), ("1 08:00", -20), ("1 10:00", -8), ("1 16:00", -6),
        ("1 18:00", -20),
        ("2 00:00", -30), ("2 03:00", -60), ("2 05:00", -85), ("2 08:45", -85),
        ("2 10:00", -15), ("2 10:30", -8), ("2 16:00", -6), ("2 18:00", -25),
        ("2 22:00", -15),
        ("3 00:00", -8), ("3 14:00", -6), ("3 22:00", -10),
        ("4 00:00", -20), ("4 04:00", 30), ("4 08:00", 25), ("4 10:00", 20),
        ("4 12:15", -8), ("4 15:45", -6), ("4 17:30", -20), ("4 21:00", -30),
        ("5 00:00", -25), ("5 10:30", -8), ("5 16:30", -6), ("5 18:00", -20),
        ("6 00:00", -15), ("6 10:00", -8), ("7 00:00", -8),
    ],
    # Dew point (F)
    "td": [
        ("1 00:00", 41.0), ("2 00:00", 42.0), ("2 22:00", 47.0), ("3 06:00", 49.0),
        ("3 14:00", 50.0), ("3 20:00", 42.0), ("4 00:00", 39.0), ("4 06:00", 36.5),
        ("4 14:00", 38.0), ("5 06:00", 38.0), ("5 14:00", 40.0), ("6 06:00", 42.0),
        ("7 00:00", 47.0),
    ],
    # Sky cover (%)
    "sky": [
        ("1 00:00", 5), ("2 14:00", 5), ("2 18:00", 30), ("2 21:00", 70),
        ("3 00:00", 90), ("3 15:00", 100), ("3 17:30", 70), ("3 20:00", 25),
        ("3 23:00", 8), ("5 23:00", 5), ("6 06:00", 30), ("6 12:00", 65),
        ("6 18:00", 85), ("7 00:00", 90),
    ],
    # Probability of precipitation (%)
    "pop": [
        ("1 00:00", 0), ("3 06:00", 5), ("3 10:00", 25), ("3 13:00", 60),
        ("3 14:30", 80), ("3 16:30", 50), ("3 18:30", 10), ("3 21:00", 0),
        ("6 12:00", 0), ("6 20:00", 20), ("7 00:00", 30),
    ],
    # Rain rate (in/hr)
    "rain": [
        ("1 00:00", 0.0), ("3 13:30", 0.0), ("3 14:15", 0.05), ("3 15:15", 0.04),
        ("3 16:15", 0.0), ("7 00:00", 0.0),
    ],
    # Barometric pressure (inHg)
    "pressure": [
        ("1 00:00", 30.12), ("2 00:00", 30.08), ("3 00:00", 29.96), ("3 14:00", 29.82),
        ("4 00:00", 30.02), ("4 12:00", 30.16), ("5 12:00", 30.14), ("6 12:00", 30.02),
        ("7 00:00", 29.94),
    ],
}

# Sensor faults injected into the tower data: (sensor height, start, end, kind)
FAULTS = [
    (30, "4 03:10", "4 04:25", "missing"),   # top sensor drops out during an inversion
    (15, "4 13:00", "4 13:40", "stale"),     # mid sensor repeats its last reading
    (5, "2 13:20", "2 13:20", "suspect"),    # single impossible temperature spike
]


def hours(label):
    day, clock = label.split()
    hh, mm = clock.split(":")
    return (int(day) - 1) * 24 + int(hh) + int(mm) / 60


def timestamp(label):
    return START + timedelta(hours=hours(label))


def iso(label):
    return timestamp(label).isoformat()


def interpolate(points, h):
    if h <= points[0][0]:
        return points[0][1]
    for (h0, v0), (h1, v1) in zip(points, points[1:]):
        if h <= h1:
            return v0 + (v1 - v0) * (h - h0) / (h1 - h0)
    return points[-1][1]


def smooth(series, half_window):
    last = len(series) - 1
    return [
        sum(series[min(max(j, 0), last)] for j in range(i - half_window, i + half_window + 1))
        / (2 * half_window + 1)
        for i in range(len(series))
    ]


def build(name, half_window, n_steps):
    points = [(hours(label), value) for label, value in KNOTS[name]]
    return smooth([interpolate(points, i / STEPS_PER_HOUR) for i in range(n_steps)], half_window)


def ar1(rng, n, phi):
    """Unit-variance autocorrelated noise, so readings drift instead of jumping."""
    scale = math.sqrt(1 - phi * phi)
    value = rng.gauss(0, 1)
    out = []
    for _ in range(n):
        out.append(value)
        value = phi * value + scale * rng.gauss(0, 1)
    return out


def relative_humidity(temp_f, dew_f):
    def saturation(f):
        c = (f - 32) / 1.8
        return math.exp(17.625 * c / (243.04 + c))
    return min(100.0, 100 * saturation(dew_f) / saturation(temp_f))


def compass(deg):
    names = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
             "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"]
    return names[round((deg % 360) / 22.5) % 16]


def is_daylight(h):
    return SUNRISE_H <= h % 24 <= SUNSET_H


def write_csv(name, rows):
    with open(OUT / name, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_json(name, payload):
    with open(OUT / name, "w") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------
def tower_rows(base, rng):
    n = TOWER_DAYS * 24 * STEPS_PER_HOUR
    regional = ar1(rng, n, 0.97)          # slow wiggle shared by every sensor
    wind_common = ar1(rng, n, 0.9)
    noise = {
        h: {"t": ar1(rng, n, 0.6), "w": ar1(rng, n, 0.7), "d": ar1(rng, n, 0.8),
            "g": ar1(rng, n, 0.5), "rh": ar1(rng, n, 0.8)}
        for h in HEIGHTS
    }
    faults = [(h, timestamp(a), timestamp(b), kind) for h, a, b, kind in FAULTS]
    battery = {5: 97.0, 15: 93.0, 30: 78.0}
    last_good = {}
    rows = []

    for i in range(n):
        ts = START + timedelta(minutes=i * STEP_MIN)
        hour = i / STEPS_PER_HOUR
        dew = min(base["td"][i], base["t5"][i] - 0.6)
        for h in HEIGHTS:
            charge = 0.07 * (1 - 0.7 * base["sky"][i] / 100) if is_daylight(hour) else -0.022
            battery[h] = min(100.0, battery[h] + charge)

            temp = (base["t5"][i] + TEMP_FRAC[h] * base["dt"][i]
                    + 0.25 * regional[i] + 0.08 * noise[h]["t"][i])
            wind_base = base["u5"][i] + WIND_FRAC[h] * (base["u30"][i] - base["u5"][i])
            wind_base *= 1 + 0.04 * wind_common[i]
            speed = max(0.0, wind_base + (0.12 + 0.025 * wind_base) * noise[h]["w"][i])
            gust_factor = 1.3 + 0.1 * abs(noise[h]["g"][i]) + 0.2 * min(1.0, base["u30"][i] / 15)
            direction = (base["d30"][i] + DIR_FRAC[h] * base["dd"][i]
                         + (3 + 12 / (1 + wind_base)) * noise[h]["d"][i])
            row = {
                "timestamp": ts.isoformat(),
                "observed_at": ts.isoformat(),
                "tower_id": "TWR1",
                "sensor_id": f"TWR1-{h:02d}",
                "height_ft": h,
                "temperature_f": round(temp, 1),
                "relative_humidity_pct": round(
                    min(100.0, relative_humidity(temp, dew) + 0.6 * noise[h]["rh"][i]), 1),
                "wind_speed_mph": round(speed, 1),
                "wind_gust_mph": round(speed * gust_factor + 0.2, 1),
                "wind_direction_deg": round(direction) % 360,
                "battery_pct": round(battery[h], 1),
                "quality": "good",
            }

            kind = next((k for fh, a, b, k in faults if fh == h and a <= ts <= b), None)
            if kind == "missing":
                for field in ("observed_at", "temperature_f", "relative_humidity_pct",
                              "wind_speed_mph", "wind_gust_mph", "wind_direction_deg",
                              "battery_pct"):
                    row[field] = ""
                row["quality"] = "missing"
            elif kind == "stale":
                row = {**last_good[h], "timestamp": ts.isoformat(), "quality": "stale"}
            elif kind == "suspect":
                row["temperature_f"] = 139.8
                row["quality"] = "suspect"
            else:
                last_good[h] = row
            rows.append(row)
    return rows


def ground_station_rows(base, rng):
    """Open-field station ~3 miles away. One height only, so it cannot see the profile."""
    every = 15 // STEP_MIN
    n = TOWER_DAYS * 24 * STEPS_PER_HOUR // every
    regional = ar1(rng, n, 0.9)
    n_t, n_w, n_d, n_g, n_s = (ar1(rng, n, phi) for phi in (0.6, 0.7, 0.8, 0.5, 0.7))
    rows = []
    for k in range(n):
        i = k * every
        hour = i / STEPS_PER_HOUR
        ts = START + timedelta(minutes=i * STEP_MIN)
        temp = (base["t5"][i] + 0.2 * max(base["dt"][i], 0) + 0.3
                + 0.25 * regional[k] + 0.1 * n_t[k])
        dew = min(base["td"][i], temp - 0.6)
        wind_base = 1.05 * base["u5"][i]
        speed = max(0.0, wind_base + (0.12 + 0.025 * wind_base) * n_w[k])
        gust_factor = 1.3 + 0.1 * abs(n_g[k]) + 0.2 * min(1.0, base["u30"][i] / 15)
        direction = (base["d30"][i] + base["dd"][i] + 5
                     + (3 + 12 / (1 + wind_base)) * n_d[k])
        solar = 0.0
        if is_daylight(hour):
            sun = math.sin(math.pi * (hour % 24 - SUNRISE_H) / (SUNSET_H - SUNRISE_H))
            solar = max(0.0, 560 * sun ** 1.2 * (1 - 0.72 * base["sky"][i] / 100) + 6 * n_s[k])
        rain = base["rain"][i] * 0.25
        rows.append({
            "timestamp": ts.isoformat(),
            "station_id": "GS-PARLIER-SIM",
            "height_ft": 6.5,
            "temperature_f": round(temp, 1),
            "relative_humidity_pct": round(relative_humidity(temp, dew), 1),
            "dew_point_f": round(dew, 1),
            "wind_speed_mph": round(speed, 1),
            "wind_gust_mph": round(speed * gust_factor + 0.2, 1),
            "wind_direction_deg": round(direction) % 360,
            "solar_radiation_wm2": round(solar),
            "precipitation_in": round(rain * (1 + 0.3 * n_s[k]), 2) if rain > 0.002 else 0.0,
            "pressure_inhg": round(base["pressure"][i] + 0.004 * regional[k], 2),
        })
    return rows


def short_forecast(sky, pop, daytime):
    if pop >= 55:
        return "Light Rain Likely"
    if pop >= 30:
        return "Chance Light Rain"
    if sky < 12:
        return "Sunny" if daytime else "Clear"
    if sky < 35:
        return "Mostly Sunny" if daytime else "Mostly Clear"
    if sky < 60:
        return "Partly Sunny" if daytime else "Partly Cloudy"
    return "Mostly Cloudy" if sky < 88 else "Cloudy"


def nws_forecast(base):
    """Regional forecast: 2 m temperature and 10 m wind only, no vertical profile.

    It is deliberately imperfect: smoother than the orchard, warmer at night than the
    orchard floor, and about 45 minutes early on wind changes.
    """
    last = len(base["t5"]) - 1
    periods = []
    for j in range(MODEL_DAYS * 24):
        mid = min(j * STEPS_PER_HOUR + STEPS_PER_HOUR // 2, last)
        wind_i = min(j * STEPS_PER_HOUR + 9, last)
        start = START + timedelta(hours=j)
        daytime = 6 <= start.hour < 18
        temp = round(base["t5"][mid] + 0.45 * max(base["dt"][mid], 0) + 0.5)
        dew = min(base["td"][mid], temp - 0.5)
        humidity = round(relative_humidity(temp, dew))
        wind = round(0.9 * base["u30"][wind_i])
        pop = int(round(base["pop"][mid] / 5) * 5)
        periods.append({
            "number": j + 1,
            "name": "",
            "startTime": start.isoformat(),
            "endTime": (start + timedelta(hours=1)).isoformat(),
            "isDaytime": daytime,
            "temperature": temp,
            "temperatureUnit": "F",
            "temperatureTrend": "",
            "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent", "value": pop},
            "dewpoint": {"unitCode": "wmoUnit:degC", "value": round((dew - 32) / 1.8, 2)},
            "relativeHumidity": {"unitCode": "wmoUnit:percent", "value": humidity},
            "windSpeed": f"{wind} mph",
            "windDirection": compass(base["d30"][wind_i]),
            "shortForecast": short_forecast(base["sky"][mid], pop, daytime),
            "detailedForecast": "",
        })
    return {
        "_note": ("SIMULATED. Shaped like the api.weather.gov hourly forecast response so the "
                  "real API can be swapped in. Temperature is ~2 m and wind is ~10 m above "
                  "open ground; there is no temperature profile, so it cannot show an inversion."),
        "type": "Feature",
        "properties": {
            "units": "us",
            "forecastGenerator": "HourlyForecastGenerator",
            "generatedAt": START.isoformat(),
            "updateTime": START.isoformat(),
            "periods": periods,
        },
    }


# ---------------------------------------------------------------------------
# Static reference data
# ---------------------------------------------------------------------------
SITE = {
    "site_id": "KRO",
    "name": "Kings River Orchards (fictional)",
    "location": {
        "nearest_town": "Parlier, CA",
        "county": "Fresno",
        "region": "San Joaquin Valley",
        "latitude": 36.611,
        "longitude": -119.527,
        "elevation_ft": 345,
    },
    "timezone": "America/Los_Angeles",
    "utc_offset": "-08:00",
    "data_period": {
        "history_start": iso("1 00:00"),
        "history_end": iso("4 23:55"),
        "forecast_end": iso("7 00:00"),
    },
    "daylight": {"sunrise_local": "06:35", "sunset_local": "16:50",
                 "note": "Approximate for mid-November at this latitude."},
    "conventions": {
        "wind_direction": "Degrees the wind blows FROM (0 = N, 90 = E).",
        "drift_direction": "Spray moves toward (wind_direction + 180) % 360.",
        "bearing_deg": "Compass bearing from the tower to the feature.",
    },
    "tower": {
        "tower_id": "TWR1",
        "block_id": "B2",
        "latitude": 36.6112,
        "longitude": -119.5268,
        "sampling_interval_minutes": STEP_MIN,
        "sensors": [
            {"sensor_id": "TWR1-05", "height_ft": 5, "position": "Below canopy, applicator height"},
            {"sensor_id": "TWR1-15", "height_ft": 15, "position": "Upper canopy"},
            {"sensor_id": "TWR1-30", "height_ft": 30, "position": "Above canopy"},
        ],
    },
    "ground_station": {
        "station_id": "GS-PARLIER-SIM",
        "description": "Single-height regional weather station in open ground.",
        "height_ft": 6.5,
        "distance_miles": 3.2,
        "bearing_deg": 250,
        "sampling_interval_minutes": 15,
    },
    "blocks": [
        {"block_id": "B1", "crop": "Orchard", "acres": 38,
         "canopy_height_ft": 20, "row_orientation": "N-S"},
        {"block_id": "B2", "crop": "Orchard", "acres": 42,
         "canopy_height_ft": 22, "row_orientation": "N-S"},
        {"block_id": "B3", "crop": "Orchard", "acres": 25,
         "canopy_height_ft": 12, "row_orientation": "E-W"},
    ],
    "sensitive_areas": [
        {"area_id": "S1", "name": "Elementary school", "type": "school",
         "bearing_deg": 8, "distance_ft": 1900},
        {"area_id": "S2", "name": "Organic vineyard (neighbor)", "type": "sensitive_crop",
         "bearing_deg": 90, "distance_ft": 200},
        {"area_id": "S3", "name": "Irrigation canal", "type": "waterway",
         "bearing_deg": 180, "distance_ft": 450},
        {"area_id": "S4", "name": "Farmworker housing", "type": "residence",
         "bearing_deg": 225, "distance_ft": 1100},
    ],
    "contacts": [
        {"contact_id": "C1", "name": "Mateo Fuentes", "role": "applicator",
         "phone": "+1-559-555-0114", "email": "mateo@example.com",
         "channels": ["sms", "push"], "notify_on": ["CAUTION", "STOP"]},
        {"contact_id": "C2", "name": "Priya Raman", "role": "pca",
         "phone": "+1-559-555-0127", "email": "priya@example.com",
         "channels": ["sms", "email"], "notify_on": ["STOP"]},
        {"contact_id": "C3", "name": "Walt Hendricks", "role": "ranch_manager",
         "phone": "+1-559-555-0139", "email": "walt@example.com",
         "channels": ["email"], "notify_on": ["STOP"]},
    ],
}

PRODUCTS = {
    "disclaimer": ("Fictional products with illustrative values for a prototype. "
                   "Real limits come from the product label and local regulations."),
    "droplet_classes": ["Fine", "Medium", "Coarse", "Very Coarse"],
    "products": [
        {"product_id": "P1", "name": "OrchardGuard 4F", "type": "fungicide",
         "formulation": "flowable", "volatility": "low", "vapor_pressure_mpa_25c": 0.002,
         "label_min_wind_mph": 3, "label_max_wind_mph": 10, "label_max_temp_f": 90,
         "inversion_spray_prohibited": True, "required_droplet_class": "Medium",
         "buffer_zone_ft": 25, "post_application_monitoring_hours": 2,
         "reentry_interval_hours": 12},
        {"product_id": "P2", "name": "MiteStop EC", "type": "miticide",
         "formulation": "emulsifiable concentrate", "volatility": "medium",
         "vapor_pressure_mpa_25c": 0.8,
         "label_min_wind_mph": 3, "label_max_wind_mph": 10, "label_max_temp_f": 85,
         "inversion_spray_prohibited": True, "required_droplet_class": "Medium",
         "buffer_zone_ft": 50, "post_application_monitoring_hours": 6,
         "reentry_interval_hours": 24},
        {"product_id": "P3", "name": "VaporMax 2E", "type": "herbicide",
         "formulation": "ester", "volatility": "high", "vapor_pressure_mpa_25c": 24.0,
         "label_min_wind_mph": 3, "label_max_wind_mph": 8, "label_max_temp_f": 80,
         "inversion_spray_prohibited": True, "required_droplet_class": "Coarse",
         "buffer_zone_ft": 150, "post_application_monitoring_hours": 24,
         "reentry_interval_hours": 48},
        {"product_id": "P4", "name": "DormantShield Oil", "type": "dormant oil",
         "formulation": "oil", "volatility": "low", "vapor_pressure_mpa_25c": 0.001,
         "label_min_wind_mph": 3, "label_max_wind_mph": 10, "label_max_temp_f": 85,
         "inversion_spray_prohibited": True, "required_droplet_class": "Coarse",
         "buffer_zone_ft": 25, "post_application_monitoring_hours": 2,
         "reentry_interval_hours": 12},
    ],
}

APPLICATIONS = [
    {"application_id": "A1", "status": "completed", "block_id": "B1", "product_id": "P1",
     "start_time": iso("1 10:00"), "end_time": iso("1 12:00"),
     "earliest_start": "", "latest_end": "", "duration_minutes": 120,
     "method": "airblast", "droplet_class": "Medium", "spray_volume_gpa": 100, "acres": 38,
     "applicator": "Mateo Fuentes", "pca": "Priya Raman",
     "notes": "Conditions stay acceptable before, during and after."},
    {"application_id": "A2", "status": "completed", "block_id": "B2", "product_id": "P3",
     "start_time": iso("2 15:00"), "end_time": iso("2 16:30"),
     "earliest_start": "", "latest_end": "", "duration_minutes": 90,
     "method": "ground boom (orchard floor)", "droplet_class": "Coarse",
     "spray_volume_gpa": 20, "acres": 42,
     "applicator": "Mateo Fuentes", "pca": "Priya Raman",
     "notes": "High-volatility product. Evening inversion forms near the end of the job "
              "and lasts through the monitoring period."},
    {"application_id": "A3", "status": "completed", "block_id": "B3", "product_id": "P2",
     "start_time": iso("3 09:00"), "end_time": iso("3 11:00"),
     "earliest_start": "", "latest_end": "", "duration_minutes": 120,
     "method": "airblast", "droplet_class": "Medium", "spray_volume_gpa": 100, "acres": 25,
     "applicator": "Mateo Fuentes", "pca": "Priya Raman",
     "notes": "Starts in acceptable conditions. Wind above the canopy climbs past 10 mph "
              "mid-job while the 5 ft wind still looks fine."},
    {"application_id": "A4", "status": "planned", "block_id": "B1", "product_id": "P4",
     "start_time": "", "end_time": "",
     "earliest_start": iso("5 06:00"), "latest_end": iso("5 18:00"), "duration_minutes": 120,
     "method": "airblast", "droplet_class": "Coarse", "spray_volume_gpa": 200, "acres": 38,
     "applicator": "Mateo Fuentes", "pca": "Priya Raman",
     "notes": "Needs a spray window. Use the forecast and recent tower history."},
    {"application_id": "A5", "status": "planned", "block_id": "B2", "product_id": "P3",
     "start_time": "", "end_time": "",
     "earliest_start": iso("6 06:00"), "latest_end": iso("6 18:00"), "duration_minutes": 90,
     "method": "ground boom (orchard floor)", "droplet_class": "Coarse",
     "spray_volume_gpa": 20, "acres": 42,
     "applicator": "Mateo Fuentes", "pca": "Priya Raman",
     "notes": "High-volatility product with an 8 mph label limit; the afternoon is "
              "forecast to turn breezy."},
]

TIMELINE = [
    ("1 00:00", "1 08:30", "calm_inversion", "no", "inversion;wind_below_3mph",
     "Clear, still night. Strong inversion and near-calm wind at every height."),
    ("1 10:00", "1 15:30", "safe_window", "yes", "",
     "Sunny, well-mixed air. No inversion, steady NW wind inside 3-10 mph, little shear."),
    ("1 16:20", "1 23:55", "evening_inversion", "no", "inversion;wind_below_3mph",
     "Inversion forms about half an hour before sunset as the wind dies."),
    ("2 05:00", "2 08:30", "hidden_inversion", "yes",
     "inversion;wind_direction_shear;wind_speed_shear",
     "PRIMARY DEMO. Easterly 4-5 mph breeze at ground level looks fine, but air at 30 ft "
     "is 3-5 F warmer and blowing from the south at about 9 mph, toward the school."),
    ("2 10:30", "2 15:45", "safe_window", "yes", "",
     "Inversion has burned off. Steady NW wind, small differences between heights."),
    ("2 13:20", "2 13:20", "sensor_suspect", "n/a", "sensor_suspect",
     "One impossible 5 ft temperature reading (139.8 F). Tests input validation."),
    ("2 15:00", "2 16:30", "application_A2", "yes", "inversion;product_volatility",
     "High-volatility product applied. Inversion starts near the end of the job."),
    ("2 16:10", "2 22:30", "post_application_inversion", "mixed",
     "inversion;product_volatility",
     "Inversion persists for hours after application A2, with 5 ft wind under 3 mph for "
     "much of the evening. Vapor drift risk after spraying."),
    ("3 00:30", "3 09:45", "overcast_night_no_inversion", "yes", "",
     "Cloudy, breezy night. No inversion forms, showing that night is not always unsafe."),
    ("3 09:00", "3 11:00", "application_A3", "yes", "wind_above_10mph;wind_speed_shear",
     "Conditions deteriorate during spraying. 30 ft wind passes 10 mph around 10:00."),
    ("3 10:15", "3 11:30", "hidden_high_wind_aloft", "yes",
     "wind_above_10mph;wind_speed_shear",
     "5 ft wind is 7-9 mph and looks fine. 30 ft wind is 11-15 mph."),
    ("3 12:15", "3 15:15", "high_wind_all_heights", "no", "wind_above_10mph;wind_speed_shear",
     "Pre-frontal wind above 10 mph at every height."),
    ("3 13:45", "3 16:15", "rain_and_wind_shift", "no", "wind_above_10mph",
     "Light rain. Wind swings from S to NW between about 14:00 and 14:45 as the front passes."),
    ("3 20:30", "3 23:55", "evening_inversion", "mixed", "inversion",
     "Skies clear behind the front and an inversion builds while the wind is still easing."),
    ("4 00:00", "4 09:00", "calm_inversion", "no", "inversion;wind_below_3mph",
     "Cold, clear, nearly calm. Inversion until mid-morning."),
    ("4 03:10", "4 04:25", "sensor_missing", "n/a", "sensor_missing",
     "30 ft sensor stops reporting. The 5 and 15 ft sensors still show the inversion."),
    ("4 10:00", "4 11:30", "low_wind_no_inversion", "no", "wind_below_3mph",
     "Inversion is gone but the air is light and variable, under 3 mph at 5 ft."),
    ("4 12:30", "4 15:30", "safe_window", "yes", "",
     "Steady NW wind inside 3-10 mph, no inversion, little shear."),
    ("4 13:00", "4 13:40", "sensor_stale", "n/a", "sensor_stale",
     "15 ft sensor repeats its 12:55 reading. observed_at stops advancing."),
    ("4 16:15", "4 23:55", "evening_inversion", "no", "inversion;wind_below_3mph",
     "Inversion re-forms before sunset."),
]


def reading(height, temp, humidity, speed, direction, quality="good", observed_at=None):
    missing = quality == "missing"
    return {
        "sensor_id": f"TWR1-{height:02d}",
        "height_ft": height,
        "temperature_f": None if missing else temp,
        "relative_humidity_pct": None if missing else humidity,
        "wind_speed_mph": None if missing else speed,
        "wind_gust_mph": None if missing else round(speed * 1.4 + 0.2, 1),
        "wind_direction_deg": None if missing else direction,
        "quality": quality,
        "observed_at": observed_at,
    }


def scenario(scenario_id, name, when, description, readings, ground, looks_ok, hazards,
             in_series=True, product_id=None):
    ts = iso(when)
    for r in readings:
        if r["quality"] == "good":
            r["observed_at"] = ts
    temp, speed, direction = ground
    return {
        "id": scenario_id,
        "name": name,
        "description": description,
        "timestamp": ts,
        "matches_time_series": in_series,
        "product_id": product_id,
        "readings": readings,
        "ground_station": {"height_ft": 6.5, "temperature_f": temp,
                           "wind_speed_mph": speed, "wind_direction_deg": direction},
        "ground_station_looks_ok": looks_ok,
        "intended_hazards": hazards,
    }


SCENARIOS = {
    "_note": ("Single snapshots for demo buttons and unit tests. intended_hazards is what each "
              "scenario was designed to show. How large a difference counts as shear, and how "
              "hazards map to Go / Caution / Stop, is your tool's policy."),
    "scenarios": [
        scenario("safe_midday", "Safe midday", "1 13:00",
                 "Well-mixed afternoon. Cooler aloft, steady NW wind, little shear.",
                 [reading(5, 64.2, 44, 5.8, 305), reading(15, 63.7, 45, 6.6, 308),
                  reading(30, 62.9, 46, 7.9, 312)],
                 (64.6, 6.1, 310), True, []),
        scenario("hidden_inversion", "Hidden inversion (primary demo)", "2 07:00",
                 "Ground wind is 4.7 mph and looks fine. Air at 30 ft is 4.9 F warmer, "
                 "almost twice as fast, and blowing from the south instead of the east.",
                 [reading(5, 45.6, 91, 4.7, 100), reading(15, 47.8, 84, 6.2, 140),
                  reading(30, 50.5, 76, 9.0, 185)],
                 (46.9, 5.0, 105), True,
                 ["inversion", "wind_direction_shear", "wind_speed_shear"]),
        scenario("calm_inversion", "Calm inversion", "1 05:30",
                 "Classic still, clear pre-dawn. Strong inversion and almost no wind.",
                 [reading(5, 42.8, 94, 0.9, 95), reading(15, 45.6, 84, 1.6, 110),
                  reading(30, 49.1, 74, 3.1, 125)],
                 (43.9, 1.1, 100), False, ["inversion", "wind_below_3mph"]),
        scenario("low_wind_no_inversion", "Low wind, no inversion", "4 10:45",
                 "Inversion has lifted but the air is light and variable.",
                 [reading(5, 52.0, 58, 2.0, 195), reading(15, 51.6, 59, 2.4, 185),
                  reading(30, 51.0, 60, 3.4, 180)],
                 (52.4, 2.2, 200), False, ["wind_below_3mph"]),
        scenario("high_wind_aloft", "High wind above the canopy", "3 11:00",
                 "5 ft wind is 8 mph. Above the canopy it is over 13 mph.",
                 [reading(5, 56.9, 77, 8.0, 160), reading(15, 56.6, 78, 10.1, 164),
                  reading(30, 56.1, 79, 13.2, 168)],
                 (57.1, 8.4, 165), True, ["wind_above_10mph", "wind_speed_shear"]),
        scenario("high_wind_all", "High wind at every height", "3 13:30",
                 "Pre-frontal wind. Too windy everywhere, and the ground station agrees.",
                 [reading(5, 59.8, 70, 12.6, 172), reading(15, 59.5, 71, 15.2, 175),
                  reading(30, 59.0, 72, 18.7, 178)],
                 (60.0, 13.4, 175), False, ["wind_above_10mph", "wind_speed_shear"]),
        scenario("direction_shear_only", "Direction shear only", "4 12:00",
                 "No inversion and speeds are in range, but the wind turns 95 degrees "
                 "between 5 ft and 30 ft.",
                 [reading(5, 58.0, 50, 4.6, 130), reading(15, 57.6, 51, 5.2, 175),
                  reading(30, 57.1, 52, 6.4, 225)],
                 (58.3, 4.9, 135), True, ["wind_direction_shear"], in_series=False),
        scenario("speed_shear_only", "Speed shear only", "1 15:00",
                 "No inversion, same direction, every speed in range, but the 30 ft wind "
                 "is 6 mph faster than the 5 ft wind.",
                 [reading(5, 60.5, 48, 3.4, 300), reading(15, 60.1, 49, 5.9, 305),
                  reading(30, 59.5, 50, 9.4, 310)],
                 (60.8, 3.7, 300), True, ["wind_speed_shear"], in_series=False),
        scenario("sensor_missing_upper", "Top sensor offline", "4 03:30",
                 "30 ft sensor is not reporting. The lower two still show an inversion.",
                 [reading(5, 40.6, 89, 0.8, 110), reading(15, 42.1, 83, 1.2, 105),
                  reading(30, None, None, None, None, quality="missing")],
                 (41.4, 0.9, 100), False,
                 ["sensor_missing", "inversion", "wind_below_3mph"]),
        scenario("sensor_stale_mid", "Mid sensor stale", "4 13:20",
                 "15 ft sensor last updated 25 minutes ago. Other heights look acceptable.",
                 [reading(5, 59.3, 45, 4.7, 312),
                  reading(15, 57.8, 47, 5.0, 314, quality="stale", observed_at=iso("4 12:55")),
                  reading(30, 57.9, 47, 6.5, 318)],
                 (59.6, 5.0, 315), True, ["sensor_stale"]),
        scenario("volatile_product_marginal", "Volatile product near its label limit", "2 14:30",
                 "Fine under the general 3-10 mph guidance. Product P3 has an 8 mph label "
                 "limit, which the 30 ft wind exceeds. The same readings with P1 are acceptable.",
                 [reading(5, 66.8, 42, 6.9, 310), reading(15, 66.3, 43, 7.8, 312),
                  reading(30, 65.9, 44, 8.9, 315)],
                 (67.1, 7.2, 312), True, ["product_label_limit"],
                 in_series=False, product_id="P3"),
        scenario("boundary_wind_3mph", "Boundary: exactly 3 mph, equal temperatures", "1 12:00",
                 "Unit-test case. Wind is exactly 3.0 mph and all temperatures are equal, "
                 "so neither 'below 3 mph' nor 'upper warmer than lower' is true.",
                 [reading(5, 55.0, 60, 3.0, 300), reading(15, 55.0, 60, 3.0, 300),
                  reading(30, 55.0, 60, 3.0, 300)],
                 (55.0, 3.0, 300), True, [], in_series=False),
        scenario("boundary_wind_10mph", "Boundary: exactly 10 mph", "1 12:00",
                 "Unit-test case. Wind is exactly 10.0 mph, so 'above 10 mph' is not true.",
                 [reading(5, 55.3, 60, 10.0, 300), reading(15, 55.1, 60, 10.0, 300),
                  reading(30, 54.9, 61, 10.0, 300)],
                 (55.4, 10.0, 300), True, [], in_series=False),
    ],
}


def main():
    OUT.mkdir(exist_ok=True)
    rng = random.Random(SEED)
    n_model = MODEL_DAYS * 24 * STEPS_PER_HOUR + 1
    windows = {"t5": 4, "dt": 2, "u30": 2, "u5": 2, "d30": 2, "dd": 2,
               "td": 3, "sky": 3, "pop": 3, "rain": 1, "pressure": 3}
    base = {name: build(name, half, n_model) for name, half in windows.items()}

    tower = tower_rows(base, rng)
    ground = ground_station_rows(base, rng)
    timeline = [
        {"start_time": iso(a), "end_time": iso(b), "label": label,
         "ground_station_looks_ok": ok, "intended_hazards": hazards, "description": text}
        for a, b, label, ok, hazards, text in TIMELINE
    ]

    write_csv("tower_readings.csv", tower)
    write_csv("ground_station.csv", ground)
    write_csv("applications.csv", APPLICATIONS)
    write_csv("timeline_annotations.csv", timeline)
    write_json("nws_forecast_hourly.json", nws_forecast(base))
    write_json("products.json", PRODUCTS)
    write_json("site.json", SITE)
    write_json("scenarios.json", SCENARIOS)

    print(f"Wrote {len(tower)} tower rows, {len(ground)} ground-station rows, "
          f"{MODEL_DAYS * 24} forecast hours to {OUT}")


if __name__ == "__main__":
    main()
