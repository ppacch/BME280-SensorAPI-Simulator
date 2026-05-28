# BME280 Python Simulator

A lightweight Python 3.14 simulator for the Bosch BME280 environmental sensor.

**Purpose:** AI-assisted engineering demonstration — not a hardware replacement.  
Demonstrates documentation-driven development, constrained generation, and human-in-the-loop validation.

---

## File Structure

```
BME280_SensorAPI_Simulator/
├── src/
│   ├── bme280_sim/
│   │   ├── __init__.py        # Public exports
│   │   ├── constants.py       # Register addresses, bitmasks, mode values
│   │   ├── calibration.py     # CalibrationData dataclass (NVM coefficients + t_fine)
│   │   ├── compensation.py    # Double-precision compensation formulas (datasheet §8.1)
│   │   └── simulator.py       # BME280Simulator class + PhysicalState
│   └── tests/
│       ├── test_compensation.py   # Unit tests for compensation math
│       └── test_simulator.py      # Integration tests for register behaviour
├── demo.py                # Runnable demonstration script
├── pytest.ini             # testpaths + pythonpath = src
├── requirements.txt       # pytest only
└── README.md
```

---

## Setup

```bash
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/Mac:
source .venv/bin/activate

pip install -r requirements.txt
```

---

## Run the Demo

```bash
python demo.py
```

Expected output:
```
=== 1. Chip Identification ===
  chip_id = 0x60  [OK]

=== 2. Forced Mode — default environment (25 °C / 101325 Pa / 50 %RH) ===
  mode after measurement = 0x00 (0x00 = sleep, as expected)
  measurement delay      = 7825 µs  (7.82 ms)
  temperature = 25.00 °C
  pressure    = 101325.0 Pa  (1013.25 hPa)
  humidity    = 50.00 %RH
...
```

---

## Run Tests

```bash
pytest -v
```

---

## Architecture

### `BME280Simulator`

Register-level simulation with a clean read/write interface:

```python
sim = BME280Simulator()

# Optional: inject custom calibration or environment
sim = BME280Simulator(
    calib=CalibrationData.typical(),
    state=PhysicalState(temperature=20.0, pressure=100000.0, humidity=45.0),
)

# Register interface
data: bytes = sim.read(reg_addr, length)
sim.write(reg_addr, [byte, ...])

# Change the physical environment at any time
sim.set_environment(temperature=30.0)
```

### Measurement Flow

```
set_environment(T, P, H)
    ↓
write ctrl_hum  → stages humidity OSR (not yet active)
    ↓
write ctrl_meas → commits humidity OSR + triggers measurement
    ↓
_do_measurement():
    invert compensation → compute adc_T, adc_P, adc_H
    pack into 0xF7..0xFE (8-byte data burst)
    ↓
read(0xF7, 8) → parse_raw() → compensate → physical values
```

### Inversion Method

To go from physical values to ADC, the simulator uses bisection search (60 iterations, ~10⁻¹⁵ precision) on the forward compensation functions. No closed-form inversion is needed.

---

## Behaviours Modelled

| Behaviour | Modelled |
|---|---|
| Chip ID register (0xD0 = 0x60) | ✓ |
| Soft reset (0xB6 → register wipe) | ✓ |
| `ctrl_hum` only activates after `ctrl_meas` write | ✓ |
| Forced mode: measure once, return to sleep | ✓ |
| Normal mode: measure on transition (simplified) | ✓ (simplified) |
| Calibration NVM registers (0x88–0xA1, 0xE1–0xE7) | ✓ |
| Data register layout (0xF7–0xFE, 8-byte burst) | ✓ |
| Double-precision compensation formulas | ✓ |
| `t_fine` coupling (T → P → H ordering) | ✓ |
| Reset-state register values | ✓ |

## Behaviours NOT Modelled

| Behaviour | Status |
|---|---|
| Real I²C / SPI bus timing | Not modelled |
| `status.measuring` bit timing | Not modelled |
| NVM copy delay after reset | Not modelled |
| Normal mode autonomous cycling | Simplified (one shot per write) |
| IIR filter state machine | Not modelled |
| Oversampling averaging | Not modelled (ADC directly inverted) |
| Sensor noise / quantisation noise | Not modelled |
| Temperature self-heating effect | Not modelled |
| 32-bit and 64-bit integer compensation paths | Not modelled (double only) |

---

## Engineering Notes

### `t_fine` Coupling

Temperature must always be compensated before pressure or humidity.  
`t_fine` is stored as a side-effect in `CalibrationData` and consumed by the P and H formulas. This mirrors the driver's `bme280_compensate_data()` function in `bme280.c`.

### ctrl_hum Quirk

Writing `ctrl_hum` (0xF2) does not take effect until a subsequent write to `ctrl_meas` (0xF4). This is documented in datasheet §5.4.3 and reproduced in `_handle_write()`.

### Calibration Data

`CalibrationData.typical()` uses representative real-world coefficients.  
Replace with device-specific values (read from actual hardware NVM) for production testing.

---

## Human Validation Required

This simulator does not validate:
- Actual hardware timing behaviour
- Real calibration coefficient correctness
- Compensation formula accuracy at temperature extremes
- Electrical interface behaviour (SPI/I²C)
- Sensor self-heating and PCB thermal coupling

**AI assisted. Human engineers validate.**
