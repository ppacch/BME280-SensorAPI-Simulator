import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent / "src"))

"""
BME280 simulator demonstration.

Shows the complete usage pattern:
  1. Chip identification (init check)
  2. Forced-mode measurement
  3. Environment change and re-measurement
  4. Normal-mode simplified usage
  5. Measurement delay calculation
"""

from bme280_sim import BME280Simulator, PhysicalState, CalibrationData
from bme280_sim import constants as C
from bme280_sim.compensation import (
    compensate_temperature,
    compensate_pressure,
    compensate_humidity,
)


# ---------------------------------------------------------------------------
# Helper: read and compensate in one call
# ---------------------------------------------------------------------------

def read_sensor(sim: BME280Simulator) -> tuple[float, float, float]:
    """Burst-read 8 bytes from 0xF7, parse, and compensate."""
    burst = sim.read(C.REG_DATA, 8)
    adc_P, adc_T, adc_H = BME280Simulator.parse_raw(burst)
    calib = sim._calib
    temp = compensate_temperature(adc_T, calib)
    pres = compensate_pressure(adc_P, calib)
    humi = compensate_humidity(adc_H, calib)
    return temp, pres, humi


def meas_delay_us(osr_t: int, osr_p: int, osr_h: int) -> int:
    """Compute required measurement wait time in µs (mirrors bme280_cal_meas_delay)."""
    osr_map = [0, 1, 2, 4, 8, 16]
    t = osr_map[min(osr_t, 5)]
    p = osr_map[min(osr_p, 5)]
    h = osr_map[min(osr_h, 5)]
    delay = C.MEAS_OFFSET_US
    if t: delay += C.MEAS_DUR_US * t
    if p: delay += C.MEAS_DUR_US * p + C.PRES_HUM_OFFSET_US
    if h: delay += C.MEAS_DUR_US * h + C.PRES_HUM_OFFSET_US
    return delay


# ---------------------------------------------------------------------------
# Demo steps
# ---------------------------------------------------------------------------

def demo_init(sim: BME280Simulator) -> None:
    print("=== 1. Chip Identification ===")
    chip_id = sim.read(C.REG_CHIP_ID, 1)[0]
    status  = "OK" if chip_id == C.CHIP_ID else "FAIL"
    print(f"  chip_id = 0x{chip_id:02X}  [{status}]")
    print()


def demo_forced_mode(sim: BME280Simulator) -> None:
    print("=== 2. Forced Mode — default environment (25 °C / 101325 Pa / 50 %RH) ===")

    # Configure: humidity OSR ×1, temperature ×1, pressure ×1
    sim.write(C.REG_CTRL_HUM,  [0x01])   # osrs_h = ×1
    sim.write(C.REG_CTRL_MEAS, [0x25])   # osrs_t=×1, osrs_p=×1, forced (0b00100101)

    mode_after = sim.read(C.REG_CTRL_MEAS, 1)[0] & C.SENSOR_MODE_MSK
    print(f"  mode after measurement = 0x{mode_after:02X} (0x00 = sleep, as expected)")

    delay = meas_delay_us(osr_t=1, osr_p=1, osr_h=1)
    print(f"  measurement delay      = {delay} µs  ({delay/1000:.2f} ms)")

    temp, pres, humi = read_sensor(sim)
    print(f"  temperature = {temp:.2f} °C")
    print(f"  pressure    = {pres:.1f} Pa  ({pres/100:.2f} hPa)")
    print(f"  humidity    = {humi:.2f} %RH")
    print()


def demo_environment_change(sim: BME280Simulator) -> None:
    print("=== 3. Environment Change — mountain summit at 30 °C / 72000 Pa / 30 %RH ===")

    sim.set_environment(temperature=30.0, pressure=72000.0, humidity=30.0)
    sim.write(C.REG_CTRL_HUM,  [0x01])
    sim.write(C.REG_CTRL_MEAS, [0x25])

    temp, pres, humi = read_sensor(sim)
    print(f"  temperature = {temp:.2f} °C")
    print(f"  pressure    = {pres:.1f} Pa  ({pres/100:.2f} hPa)")
    print(f"  humidity    = {humi:.2f} %RH")
    print()


def demo_normal_mode(sim: BME280Simulator) -> None:
    print("=== 4. Normal Mode — simulated temperature sweep ===")
    print("  (normal mode simplified: each set_environment + ctrl_meas write = one cycle)")

    sim.write(C.REG_CTRL_HUM,  [0x01])
    sim.write(C.REG_CTRL_MEAS, [0x27])   # normal mode (0b00100111)

    for t in (20.0, 22.5, 25.0, 27.5, 30.0):
        sim.set_environment(temperature=t)
        sim.write(C.REG_CTRL_MEAS, [0x27])   # re-trigger (simplified normal mode)
        temp, pres, _ = read_sensor(sim)
        print(f"  set={t:5.1f} C  -> read={temp:.2f} C  |  {pres:.0f} Pa")
    print()


def demo_soft_reset(sim: BME280Simulator) -> None:
    print("=== 5. Soft Reset ===")
    sim.write(C.REG_CTRL_MEAS, [0xFF])
    before = sim.read(C.REG_CTRL_MEAS, 1)[0]
    sim.write(C.REG_RESET, [C.SOFT_RESET_CMD])
    after  = sim.read(C.REG_CTRL_MEAS, 1)[0]
    print(f"  ctrl_meas before reset = 0x{before:02X}")
    print(f"  ctrl_meas after  reset = 0x{after:02X}  (registers cleared)")
    print()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sim = BME280Simulator()

    demo_init(sim)
    demo_forced_mode(sim)
    demo_environment_change(sim)
    demo_normal_mode(sim)
    demo_soft_reset(sim)

    print("Done. All steps completed without hardware.")
