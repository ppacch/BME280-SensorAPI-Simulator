"""
BME280 double-precision compensation formulas.

Source: Bosch BME280 datasheet v1.24, Appendix 8.1.

Ordering constraint (from datasheet §4.2.3 and driver bme280.c):
    Temperature MUST be compensated first — it sets calib.t_fine,
    which pressure and humidity compensation both depend on.
"""

from .calibration import CalibrationData


def compensate_temperature(adc_T: int, calib: CalibrationData) -> float:
    """
    Return compensated temperature in °C, clamped to [-40, +85].

    Side-effect: sets calib.t_fine for subsequent P/H compensation.
    """
    var1 = adc_T / 16384.0 - calib.dig_T1 / 1024.0
    var1 *= calib.dig_T2
    var2 = (adc_T / 131072.0 - calib.dig_T1 / 8192.0) ** 2
    var2 *= calib.dig_T3
    calib.t_fine = int(var1 + var2)
    temperature = (var1 + var2) / 5120.0
    return max(-40.0, min(85.0, temperature))


def compensate_pressure(adc_P: int, calib: CalibrationData) -> float:
    """
    Return compensated pressure in Pa, clamped to [30000, 110000].

    Requires calib.t_fine set by a prior compensate_temperature() call.
    """
    var1 = calib.t_fine / 2.0 - 64000.0
    var2 = var1 * var1 * calib.dig_P6 / 32768.0
    var2 = var2 + var1 * calib.dig_P5 * 2.0
    var2 = var2 / 4.0 + calib.dig_P4 * 65536.0
    var3 = calib.dig_P3 * var1 * var1 / 524288.0
    var1 = (var3 + calib.dig_P2 * var1) / 524288.0
    var1 = (1.0 + var1 / 32768.0) * calib.dig_P1
    if var1 <= 0.0:
        return 30000.0
    pressure = 1048576.0 - adc_P
    pressure = (pressure - var2 / 4096.0) * 6250.0 / var1
    var1 = calib.dig_P9 * pressure * pressure / 2147483648.0
    var2 = pressure * calib.dig_P8 / 32768.0
    pressure += (var1 + var2 + calib.dig_P7) / 16.0
    return max(30000.0, min(110000.0, pressure))


def compensate_humidity(adc_H: int, calib: CalibrationData) -> float:
    """
    Return compensated relative humidity in %RH, clamped to [0, 100].

    Requires calib.t_fine set by a prior compensate_temperature() call.
    """
    var1 = calib.t_fine - 76800.0
    var2 = calib.dig_H4 * 64.0 + calib.dig_H5 / 16384.0 * var1
    var3 = adc_H - var2
    var4 = calib.dig_H2 / 65536.0
    var5 = 1.0 + calib.dig_H3 / 67108864.0 * var1
    var6 = 1.0 + calib.dig_H6 / 67108864.0 * var1 * var5
    var6 = var3 * var4 * (var5 * var6)
    humidity = var6 * (1.0 - calib.dig_H1 * var6 / 524288.0)
    return max(0.0, min(100.0, humidity))
