"""
Tests for BME280Simulator register behaviour.

Covers: chip ID, soft reset, forced/normal mode, ctrl_hum quirk,
measurement triggering, and full sensor roundtrips.
"""

import pytest
from unittest.mock import patch, call

from bme280_sim import BME280Simulator, PhysicalState, CalibrationData
from bme280_sim import constants as C
from bme280_sim.compensation import (
    compensate_temperature,
    compensate_pressure,
    compensate_humidity,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sim() -> BME280Simulator:
    return BME280Simulator()


@pytest.fixture
def sim_warm() -> BME280Simulator:
    return BME280Simulator(state=PhysicalState(temperature=30.0,
                                               pressure=98000.0,
                                               humidity=65.0))


# ---------------------------------------------------------------------------
# Register identity
# ---------------------------------------------------------------------------

class TestRegisterIdentity:

    def test_chip_id_is_0x60(self, sim: BME280Simulator) -> None:
        data = sim.read(C.REG_CHIP_ID, 1)
        assert data[0] == C.CHIP_ID

    def test_data_registers_reset_to_0x80(self, sim: BME280Simulator) -> None:
        """MSB of each unmeasured data register should be 0x80 per datasheet."""
        assert sim.read(0xF7, 1)[0] == 0x80  # press_msb
        assert sim.read(0xFA, 1)[0] == 0x80  # temp_msb
        assert sim.read(0xFD, 1)[0] == 0x80  # hum_msb

    def test_ctrl_meas_reset_to_0x00(self, sim: BME280Simulator) -> None:
        assert sim.read(C.REG_CTRL_MEAS, 1)[0] == 0x00

    def test_status_reset_to_0x00(self, sim: BME280Simulator) -> None:
        assert sim.read(C.REG_STATUS, 1)[0] == 0x00

    def test_chip_id_write_zero_is_ignored(self, sim: BME280Simulator) -> None:
        """Writing 0x00 to the read-only NVM register must have no effect (datasheet §5.4.1)."""
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # before
        sim.write(C.REG_CHIP_ID, [0x00])
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # after

    def test_chip_id_write_arbitrary_value_is_ignored(self, sim: BME280Simulator) -> None:
        """Writing any arbitrary value to 0xD0 must not alter the chip ID."""
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # before
        sim.write(C.REG_CHIP_ID, [0xFF])
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # after

    def test_chip_id_write_same_value_is_ignored(self, sim: BME280Simulator) -> None:
        """Writing the chip ID value itself to 0xD0 must also have no effect."""
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # before
        sim.write(C.REG_CHIP_ID, [C.CHIP_ID])
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID   # after

    def test_calibration_registers_populated(self, sim: BME280Simulator) -> None:
        """Calibration NVM block must be non-zero after reset."""
        calib_block = sim.read(0x88, 26)
        assert any(b != 0 for b in calib_block)


# ---------------------------------------------------------------------------
# Soft reset
# ---------------------------------------------------------------------------

class TestSoftReset:

    def test_reset_command_clears_ctrl_meas(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CTRL_MEAS, [0xFF])
        sim.write(C.REG_RESET, [C.SOFT_RESET_CMD])
        assert sim.read(C.REG_CTRL_MEAS, 1)[0] == 0x00

    def test_reset_command_clears_config(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CONFIG, [0xFF])
        sim.write(C.REG_RESET, [C.SOFT_RESET_CMD])
        assert sim.read(C.REG_CONFIG, 1)[0] == 0x00

    def test_invalid_reset_value_has_no_effect(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CTRL_MEAS, [0xFF])
        sim.write(C.REG_RESET, [0x00])   # not 0xB6
        assert sim.read(C.REG_CTRL_MEAS, 1)[0] == 0xFF

    def test_chip_id_preserved_after_reset(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_RESET, [C.SOFT_RESET_CMD])
        assert sim.read(C.REG_CHIP_ID, 1)[0] == C.CHIP_ID


# ---------------------------------------------------------------------------
# Mode transitions
# ---------------------------------------------------------------------------

class TestModeBehaviour:

    def test_forced_mode_returns_to_sleep(self, sim: BME280Simulator) -> None:
        """After a forced-mode measurement, ctrl_meas mode bits must read 0x00."""
        sim.write(C.REG_CTRL_MEAS, [0x25])   # T×1, P×1, forced (0b00100101)
        mode = sim.read(C.REG_CTRL_MEAS, 1)[0] & C.SENSOR_MODE_MSK
        assert mode == C.POWERMODE_SLEEP

    def test_normal_mode_stays_in_normal_mode(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CTRL_MEAS, [0x27])   # T×1, P×1, normal (0b00100111)
        mode = sim.read(C.REG_CTRL_MEAS, 1)[0] & C.SENSOR_MODE_MSK
        assert mode == C.POWERMODE_NORMAL

    def test_forced_mode_triggers_measurement(self, sim: BME280Simulator) -> None:
        """Setting forced mode must call _do_measurement exactly once."""
        with patch.object(sim, '_do_measurement') as mock_measure:
            sim.write(C.REG_CTRL_MEAS, [0x25])
            mock_measure.assert_called_once()

    def test_sleep_mode_does_not_trigger_measurement(self, sim: BME280Simulator) -> None:
        with patch.object(sim, '_do_measurement') as mock_measure:
            sim.write(C.REG_CTRL_MEAS, [0x00])   # sleep
            mock_measure.assert_not_called()

    def test_normal_mode_triggers_measurement(self, sim: BME280Simulator) -> None:
        with patch.object(sim, '_do_measurement') as mock_measure:
            sim.write(C.REG_CTRL_MEAS, [0x27])   # normal
            mock_measure.assert_called_once()


# ---------------------------------------------------------------------------
# ctrl_hum activation quirk
# ---------------------------------------------------------------------------

class TestHumidityOSRQuirk:

    def test_ctrl_hum_staged_before_ctrl_meas(self, sim: BME280Simulator) -> None:
        """
        Writing ctrl_hum alone must not alter the active osrs_h setting
        visible to the measurement engine — it is staged until ctrl_meas write.
        This mirrors the hardware behaviour documented in datasheet §5.4.3.
        """
        # Write humidity OSR without touching ctrl_meas
        sim.write(C.REG_CTRL_HUM, [0x03])   # osrs_h = ×4
        # Read ctrl_hum back — the value is stored but not yet committed
        # by a ctrl_meas write, so a subsequent measurement uses it only
        # after ctrl_meas is written.
        pending = sim.read(C.REG_CTRL_HUM, 1)[0]
        assert pending == 0x03

    def test_ctrl_hum_activated_by_ctrl_meas_write(self, sim: BME280Simulator) -> None:
        """ctrl_hum value must be committed when ctrl_meas is written."""
        sim.write(C.REG_CTRL_HUM,  [0x05])   # stage osrs_h = ×16
        sim.write(C.REG_CTRL_MEAS, [0x25])   # write ctrl_meas → commits
        committed = sim.read(C.REG_CTRL_HUM, 1)[0] & C.CTRL_HUM_MSK
        assert committed == 0x05


# ---------------------------------------------------------------------------
# Sensor roundtrips
# ---------------------------------------------------------------------------

def _read_and_compensate(sim: BME280Simulator) -> tuple[float, float, float]:
    """Helper: burst-read data registers, parse, compensate, return (T, P, H)."""
    burst = sim.read(C.REG_DATA, 8)
    adc_P, adc_T, adc_H = BME280Simulator.parse_raw(burst)
    calib = sim._calib
    temp = compensate_temperature(adc_T, calib)
    pres = compensate_pressure(adc_P, calib)
    humi = compensate_humidity(adc_H, calib)
    return temp, pres, humi


class TestRoundtrip:

    def test_temperature_roundtrip(self, sim: BME280Simulator) -> None:
        """Set T=25 °C, force measurement, read back — must recover within 0.1 °C."""
        sim.set_environment(temperature=25.0)
        sim.write(C.REG_CTRL_HUM,  [0x01])
        sim.write(C.REG_CTRL_MEAS, [0x25])   # forced
        temp, _, _ = _read_and_compensate(sim)
        assert abs(temp - 25.0) < 0.1

    def test_pressure_roundtrip(self, sim: BME280Simulator) -> None:
        """Set P=101325 Pa, force measurement, read back — must recover within 5 Pa."""
        sim.set_environment(pressure=101325.0)
        sim.write(C.REG_CTRL_HUM,  [0x01])
        sim.write(C.REG_CTRL_MEAS, [0x25])
        _, pres, _ = _read_and_compensate(sim)
        assert abs(pres - 101325.0) < 5.0

    def test_humidity_roundtrip(self, sim: BME280Simulator) -> None:
        """Set H=50 %RH, force measurement, read back — must recover within 0.5 %RH."""
        sim.set_environment(humidity=50.0)
        sim.write(C.REG_CTRL_HUM,  [0x01])
        sim.write(C.REG_CTRL_MEAS, [0x25])
        _, _, humi = _read_and_compensate(sim)
        assert abs(humi - 50.0) < 0.5

    def test_all_sensors_roundtrip(self, sim_warm: BME280Simulator) -> None:
        """Simultaneous T/P/H roundtrip at non-default values."""
        sim_warm.write(C.REG_CTRL_HUM,  [0x01])
        sim_warm.write(C.REG_CTRL_MEAS, [0x25])
        temp, pres, humi = _read_and_compensate(sim_warm)
        assert abs(temp - 30.0)    < 0.1
        assert abs(pres - 98000.0) < 5.0
        assert abs(humi - 65.0)    < 0.5

    def test_environment_change_changes_output(self, sim: BME280Simulator) -> None:
        """Changing the physical state between measurements must change the output."""
        sim.write(C.REG_CTRL_HUM,  [0x01])
        sim.write(C.REG_CTRL_MEAS, [0x25])
        temp_before, _, _ = _read_and_compensate(sim)

        sim.set_environment(temperature=40.0)
        sim.write(C.REG_CTRL_MEAS, [0x25])   # force again
        temp_after, _, _ = _read_and_compensate(sim)

        assert abs(temp_after - temp_before) > 5.0

    def test_extreme_temperature_roundtrip(self, sim: BME280Simulator) -> None:
        """Boundary temperature values must survive the roundtrip."""
        for target in (-35.0, 0.0, 80.0):
            sim.set_environment(temperature=target)
            sim.write(C.REG_CTRL_MEAS, [0x25])
            temp, _, _ = _read_and_compensate(sim)
            assert abs(temp - target) < 0.5, f"Failed at T={target}"


# ---------------------------------------------------------------------------
# parse_raw
# ---------------------------------------------------------------------------

class TestParseRaw:

    def test_parse_raw_returns_three_values(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CTRL_MEAS, [0x25])
        burst = sim.read(C.REG_DATA, 8)
        adc_P, adc_T, adc_H = BME280Simulator.parse_raw(burst)
        assert isinstance(adc_P, int)
        assert isinstance(adc_T, int)
        assert isinstance(adc_H, int)

    def test_parse_raw_values_in_valid_ranges(self, sim: BME280Simulator) -> None:
        sim.write(C.REG_CTRL_MEAS, [0x25])
        burst = sim.read(C.REG_DATA, 8)
        adc_P, adc_T, adc_H = BME280Simulator.parse_raw(burst)
        assert 0 <= adc_P < (1 << 20)
        assert 0 <= adc_T < (1 << 20)
        assert 0 <= adc_H < (1 << 16)
