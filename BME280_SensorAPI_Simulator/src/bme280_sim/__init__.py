"""BME280 Python simulator package."""

from .simulator import BME280Simulator, PhysicalState
from .calibration import CalibrationData
from .compensation import compensate_temperature, compensate_pressure, compensate_humidity
from . import constants

__all__ = [
    "BME280Simulator",
    "PhysicalState",
    "CalibrationData",
    "compensate_temperature",
    "compensate_pressure",
    "compensate_humidity",
    "constants",
]
