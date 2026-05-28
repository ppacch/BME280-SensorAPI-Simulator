"""
BME280 register-level software simulator.

Models the sensor's register map, mode state machine, measurement flow,
and compensation pipeline as documented in the Bosch BME280 datasheet v1.24.

Scope: demonstration and driver testing.
Not a hardware replacement — see README for modelling limitations.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import constants as C
from .calibration import CalibrationData
from .compensation import (
    compensate_temperature,
    compensate_pressure,
    compensate_humidity,
)


@dataclass
class PhysicalState:
    """Simulated physical environment the sensor is exposed to."""
    temperature: float = 25.0     # °C      [-40, +85]
    pressure:    float = 101325.0 # Pa      [30000, 110000]
    humidity:    float = 50.0     # %RH     [0, 100]


class BME280Simulator:
    """
    Register-level BME280 simulator.

    Implements the same register interface as the real device:
        read(reg_addr, length) -> bytes
        write(reg_addr, data)

    Key behaviours modelled:
    - Chip-ID register (0xD0 = 0x60)
    - Soft reset (0xB6 to 0xE0) with register wipe
    - ctrl_hum → ctrl_meas activation quirk
    - Forced mode: one measurement, auto-return to sleep
    - Normal mode: measurement triggered on mode write (simplified)
    - Calibration NVM registers (0x88-0xA1, 0xE1-0xE7)
    - Data registers (0xF7-0xFE) populated from inverse compensation

    Usage:
        sim = BME280Simulator()
        sim.set_environment(temperature=30.0, pressure=98000.0, humidity=65.0)
        sim.write(C.REG_CTRL_HUM,  [0x01])  # humidity OSR ×1
        sim.write(C.REG_CTRL_MEAS, [0x25])  # T×1, P×1, forced mode
        raw = sim.read(C.REG_DATA, 8)
    """

    def __init__(
        self,
        calib: CalibrationData | None = None,
        state: PhysicalState | None = None,
    ) -> None:
        self._calib = calib or CalibrationData.typical()
        self._state = state or PhysicalState()
        self._regs: dict[int, int] = {}
        self._pending_hum_osr: int = 0
        self._reset()

    # ------------------------------------------------------------------
    # Public register interface
    # ------------------------------------------------------------------

    def read(self, reg_addr: int, length: int = 1) -> bytes:
        """Read `length` bytes starting at `reg_addr` (auto-incrementing)."""
        return bytes(self._regs.get(reg_addr + i, 0x00) for i in range(length))

    def write(self, reg_addr: int, data: bytes | list[int]) -> None:
        """Write bytes to consecutive registers starting at `reg_addr`."""
        for offset, byte in enumerate(data):
            self._handle_write(reg_addr + offset, int(byte) & 0xFF)

    # ------------------------------------------------------------------
    # Environment control
    # ------------------------------------------------------------------

    def set_environment(
        self,
        temperature: float | None = None,
        pressure:    float | None = None,
        humidity:    float | None = None,
    ) -> None:
        """Update one or more physical environment values."""
        if temperature is not None:
            self._state.temperature = temperature
        if pressure is not None:
            self._state.pressure = pressure
        if humidity is not None:
            self._state.humidity = humidity

    # ------------------------------------------------------------------
    # Internal register dispatch
    # ------------------------------------------------------------------

    def _handle_write(self, addr: int, value: int) -> None:
        if addr == C.REG_CHIP_ID:
            return  # read-only hardware register

        if addr == C.REG_RESET:
            if value == C.SOFT_RESET_CMD:
                self._reset()
            return  # writes other than 0xB6 have no effect

        if addr == C.REG_CTRL_HUM:
            # Stage humidity OSR; becomes active only after next ctrl_meas write
            self._pending_hum_osr = value & C.CTRL_HUM_MSK
            self._regs[addr] = self._pending_hum_osr
            return

        if addr == C.REG_CTRL_MEAS:
            # Commit staged humidity OSR (ctrl_hum activation quirk)
            self._regs[C.REG_CTRL_HUM] = self._pending_hum_osr
            self._regs[addr] = value
            mode = value & C.SENSOR_MODE_MSK
            if mode in (C.POWERMODE_FORCED, 0x02):
                self._do_measurement()
                # Forced mode: sensor hardware auto-returns to sleep
                self._regs[addr] = value & ~C.SENSOR_MODE_MSK
            elif mode == C.POWERMODE_NORMAL:
                # Normal mode simplified: one measurement on transition
                self._do_measurement()
            return

        self._regs[addr] = value

    def _reset(self) -> None:
        """Apply power-on-reset state to all registers."""
        self._regs = {
            C.REG_CHIP_ID:   C.CHIP_ID,
            C.REG_RESET:     0x00,
            C.REG_CTRL_HUM:  0x00,
            C.REG_STATUS:    0x00,
            C.REG_CTRL_MEAS: 0x00,
            C.REG_CONFIG:    0x00,
            # Data registers reset state per datasheet Table 18
            0xF7: 0x80, 0xF8: 0x00, 0xF9: 0x00,
            0xFA: 0x80, 0xFB: 0x00, 0xFC: 0x00,
            0xFD: 0x80, 0xFE: 0x00,
        }
        self._pending_hum_osr = 0
        self._encode_calibration_registers()

    def _encode_calibration_registers(self) -> None:
        """Write calibration coefficients into NVM register space."""
        c = self._calib
        tp_coeffs: list[tuple[int, bool]] = [
            (c.dig_T1, False), (c.dig_T2, True),  (c.dig_T3, True),
            (c.dig_P1, False), (c.dig_P2, True),  (c.dig_P3, True),
            (c.dig_P4, True),  (c.dig_P5, True),  (c.dig_P6, True),
            (c.dig_P7, True),  (c.dig_P8, True),  (c.dig_P9, True),
        ]
        addr = 0x88
        for val, _signed in tp_coeffs:
            raw = val & 0xFFFF
            self._regs[addr]     = raw & 0xFF
            self._regs[addr + 1] = (raw >> 8) & 0xFF
            addr += 2
        self._regs[0xA1] = c.dig_H1 & 0xFF
        self._regs[0xE1] = c.dig_H2 & 0xFF
        self._regs[0xE2] = (c.dig_H2 >> 8) & 0xFF
        self._regs[0xE3] = c.dig_H3 & 0xFF
        # dig_H4 and dig_H5 share byte 0xE5 (non-aligned packing per datasheet §4.2.2)
        self._regs[0xE4] = (c.dig_H4 >> 4) & 0xFF
        self._regs[0xE5] = ((c.dig_H4 & 0x0F) | ((c.dig_H5 & 0x0F) << 4)) & 0xFF
        self._regs[0xE6] = (c.dig_H5 >> 4) & 0xFF
        self._regs[0xE7] = c.dig_H6 & 0xFF

    # ------------------------------------------------------------------
    # Measurement engine
    # ------------------------------------------------------------------

    def _do_measurement(self) -> None:
        """Compute raw ADC values from physical state and populate data registers."""
        adc_T = _invert(self._temperature_forward, self._state.temperature,
                        lo=0, hi=(1 << 20) - 1, increasing=True)
        # Run forward temperature to populate t_fine before P/H inversion
        compensate_temperature(adc_T, self._calib)

        adc_P = _invert(self._pressure_forward, self._state.pressure,
                        lo=0, hi=(1 << 20) - 1, increasing=False)
        adc_H = _invert(self._humidity_forward, self._state.humidity,
                        lo=0, hi=(1 << 16) - 1, increasing=True)

        self._pack_data_registers(adc_P, adc_T, adc_H)

    def _pack_data_registers(self, adc_P: int, adc_T: int, adc_H: int) -> None:
        """Encode 20-bit P, 20-bit T, 16-bit H into the 8-byte data burst."""
        self._regs[0xF7] = (adc_P >> 12) & 0xFF
        self._regs[0xF8] = (adc_P >> 4)  & 0xFF
        self._regs[0xF9] = (adc_P & 0x0F) << 4
        self._regs[0xFA] = (adc_T >> 12) & 0xFF
        self._regs[0xFB] = (adc_T >> 4)  & 0xFF
        self._regs[0xFC] = (adc_T & 0x0F) << 4
        self._regs[0xFD] = (adc_H >> 8) & 0xFF
        self._regs[0xFE] =  adc_H        & 0xFF

    # ------------------------------------------------------------------
    # Forward compensation wrappers (for inversion)
    # ------------------------------------------------------------------

    def _temperature_forward(self, adc_T: int) -> float:
        c = self._calib
        var1 = adc_T / 16384.0 - c.dig_T1 / 1024.0
        var1 *= c.dig_T2
        var2 = (adc_T / 131072.0 - c.dig_T1 / 8192.0) ** 2 * c.dig_T3
        return (var1 + var2) / 5120.0

    def _pressure_forward(self, adc_P: int) -> float:
        return compensate_pressure(adc_P, self._calib)

    def _humidity_forward(self, adc_H: int) -> float:
        return compensate_humidity(adc_H, self._calib)

    # ------------------------------------------------------------------
    # Helpers for readback (used in tests and demo)
    # ------------------------------------------------------------------

    @staticmethod
    def parse_raw(burst: bytes) -> tuple[int, int, int]:
        """
        Parse 8-byte burst read from 0xF7 into (adc_P, adc_T, adc_H).
        Mirrors the parse_sensor_data() function in bme280.c.
        """
        adc_P = (burst[0] << 12) | (burst[1] << 4) | (burst[2] >> 4)
        adc_T = (burst[3] << 12) | (burst[4] << 4) | (burst[5] >> 4)
        adc_H = (burst[6] << 8)  |  burst[7]
        return adc_P, adc_T, adc_H


# ------------------------------------------------------------------
# Bisection helper
# ------------------------------------------------------------------

def _invert(
    fn: Callable[[int], float],
    target: float,
    lo: int,
    hi: int,
    increasing: bool,
    iterations: int = 60,
) -> int:
    """
    Find integer x in [lo, hi] such that fn(x) ≈ target.

    Uses binary search. For an increasing function, returns the smallest x
    where fn(x) >= target. For a decreasing function, returns the smallest x
    where fn(x) <= target.
    """
    for _ in range(iterations):
        if lo >= hi:
            break
        mid = (lo + hi) // 2
        result = fn(mid)
        if increasing:
            if result < target:
                lo = mid + 1
            else:
                hi = mid
        else:
            if result > target:
                lo = mid + 1
            else:
                hi = mid
    return lo
