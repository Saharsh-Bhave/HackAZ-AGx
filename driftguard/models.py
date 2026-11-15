"""Typed data models shared by the risk engine, UI, and spray log."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, IntEnum


class Status(IntEnum):
    GO = 0
    CAUTION = 1
    STOP = 2


class Volatility(str, Enum):
    LOW = "Low"
    MODERATE = "Moderate"
    HIGH = "High"


class DropletSize(str, Enum):
    COARSE = "Coarse"
    MEDIUM = "Medium"
    FINE = "Fine"


@dataclass(frozen=True)
class SensorReading:
    height_ft: float
    temperature_f: float
    wind_speed_mph: float
    wind_direction_deg: float


@dataclass(frozen=True)
class WeatherReading:
    lower_temp_f: float
    upper_temp_f: float
    lower_wind_mph: float
    upper_wind_mph: float
    lower_direction_deg: float
    upper_direction_deg: float
    lower_height_ft: float = 5.0
    upper_height_ft: float = 30.0


@dataclass(frozen=True)
class ApplicationSettings:
    product_name: str = "Unspecified product"
    volatility: Volatility = Volatility.MODERATE
    droplet_size: DropletSize = DropletSize.COARSE


@dataclass(frozen=True)
class RiskThresholds:
    minimum_wind_mph: float = 3.0
    maximum_wind_mph: float = 10.0
    speed_shear_mph: float = 5.0
    direction_shear_deg: float = 45.0


@dataclass(frozen=True)
class Alert:
    code: str
    status: Status
    title: str
    explanation: str


@dataclass(frozen=True)
class RiskFlags:
    inversion: bool = False
    wind_below_minimum: bool = False
    wind_above_maximum: bool = False
    wind_speed_shear: bool = False
    wind_direction_shear: bool = False


@dataclass(frozen=True)
class Assessment:
    status: Status
    alerts: tuple[Alert, ...] = field(default_factory=tuple)
    flags: RiskFlags = field(default_factory=RiskFlags)
    inversion_delta_f: float = 0.0
    wind_speed_delta_mph: float = 0.0
    wind_direction_delta_deg: float = 0.0
    recommendation: str = ""
