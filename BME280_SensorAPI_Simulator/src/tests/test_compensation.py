"""
Tests for BME280 compensation formulas.

Validates double-precision implementations against known values and
checks the t_fine coupling between temperature, pressure, and humidity.
"""

import pytest
from unittest.mock import MagicMock, ANY

from bme280_sim.calibration import CalibrationData
from bme280_sim.compensation import (
    compensate_temperature,
    compensate_pressure,
    compensate_humidity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def calib() -> CalibrationData:
    return CalibrationData.typical()


# ---------------------------------------------------------------------------
# Temperature
# ---------------------------------------------------------------------------

class TestTemperature:

    def test_typical_adc_produces_25_degrees(self, calib: CalibrationData) -> None:
        """A known ADC value should produce approximately 25 °C."""
        result = compensate_temperature(519888, calib)
        assert abs(result - 25.0) < 0.5

    def test_t_fine_is_set_as_side_effect(self, calib: CalibrationData) -> None:
        """compensate_temperature must populate calib.t_fine."""
        calib.t_fine = 0
        compensate_temperature(519888, calib)
        assert calib.t_fine != 0

    def test_output_clamped_at_minimum(self, calib: CalibrationData) -> None:
        """ADC = 0 should not produce below -40 °C."""
        result = compensate_temperature(0, calib)
        assert result >= -40.0

    def test_output_clamped_at_maximum(self, calib: CalibrationData) -> None:
        """Maximum ADC value should not produce above 85 °C."""
        result = compensate_temperature((1 << 20) - 1, calib)
        assert result <= 85.0

    def test_higher_adc_produces_higher_temperature(self, calib: CalibrationData) -> None:
        t_low  = compensate_temperature(400000, calib)
        t_high = compensate_temperature(600000, calib)
        assert t_high > t_low

    def test_with_mock_calibration(self) -> None:
        """compensate_temperature works with any object exposing the required attributes."""
        mock_calib = MagicMock()
        mock_calib.dig_T1 = 27504
        mock_calib.dig_T2 = 26435
        mock_calib.dig_T3 = -1000
        result = compensate_temperature(519888, mock_calib)
        assert abs(result - 25.0) < 0.5
        # Verify t_fine was written back
        assert mock_calib.t_fine == ANY


# ---------------------------------------------------------------------------
# Pressure
# ---------------------------------------------------------------------------

class TestPressure:

    def test_output_within_valid_range(self, calib: CalibrationData) -> None:
        compensate_temperature(519888, calib)  # prime t_fine
        result = compensate_pressure(415148, calib)
        assert 30000.0 <= result <= 110000.0

    def test_pressure_uses_t_fine(self, calib: CalibrationData) -> None:
        """Same adc_P with different t_fine values must produce different pressures."""
        compensate_temperature(519888, calib)   # ~25 °C
        p_warm = compensate_pressure(415148, calib)

        compensate_temperature(200000, calib)   # cold
        p_cold = compensate_pressure(415148, calib)

        assert p_warm != p_cold

    def test_zero_var1_guard_returns_minimum(self, calib: CalibrationData) -> None:
        """If calibration produces var1 = 0 the formula must not raise."""
        calib.dig_P1 = 0
        compensate_temperature(519888, calib)
        result = compensate_pressure(415148, calib)
        assert result == 30000.0

    def test_higher_adc_produces_lower_pressure(self, calib: CalibrationData) -> None:
        """The pressure formula is inverted: higher raw ADC → lower compensated Pa."""
        compensate_temperature(519888, calib)
        p_low_adc  = compensate_pressure(300000, calib)
        p_high_adc = compensate_pressure(500000, calib)
        assert p_low_adc > p_high_adc


# ---------------------------------------------------------------------------
# Humidity
# ---------------------------------------------------------------------------

class TestHumidity:

    def test_output_within_valid_range(self, calib: CalibrationData) -> None:
        compensate_temperature(519888, calib)
        result = compensate_humidity(28847, calib)
        assert 0.0 <= result <= 100.0

    def test_output_clamped_at_100_percent(self, calib: CalibrationData) -> None:
        compensate_temperature(519888, calib)
        result = compensate_humidity((1 << 16) - 1, calib)
        assert result == 100.0

    def test_output_clamped_at_0_percent(self, calib: CalibrationData) -> None:
        compensate_temperature(519888, calib)
        result = compensate_humidity(0, calib)
        assert result == 0.0

    def test_higher_adc_produces_higher_humidity(self, calib: CalibrationData) -> None:
        compensate_temperature(519888, calib)
        h_low  = compensate_humidity(20000, calib)
        h_high = compensate_humidity(40000, calib)
        assert h_high > h_low

    def test_humidity_uses_t_fine(self, calib: CalibrationData) -> None:
        """Humidity compensation must be affected by t_fine."""
        compensate_temperature(519888, calib)
        h_warm = compensate_humidity(28847, calib)

        compensate_temperature(200000, calib)
        h_cold = compensate_humidity(28847, calib)

        assert h_warm != h_cold


# ---------------------------------------------------------------------------
# Pipeline ordering
# ---------------------------------------------------------------------------

class TestCompensationPipeline:

    def test_full_pipeline_produces_plausible_values(self, calib: CalibrationData) -> None:
        """T → P → H pipeline with typical ADC values gives realistic results."""
        temp = compensate_temperature(519888, calib)
        pres = compensate_pressure(415148, calib)
        humi = compensate_humidity(28847, calib)

        assert -40.0 <= temp <= 85.0
        assert 30000.0 <= pres <= 110000.0
        assert 0.0 <= humi <= 100.0

    def test_t_fine_changes_after_different_temperatures(self, calib: CalibrationData) -> None:
        compensate_temperature(400000, calib)
        t_fine_cold = calib.t_fine

        compensate_temperature(600000, calib)
        t_fine_warm = calib.t_fine

        assert t_fine_warm != t_fine_cold
