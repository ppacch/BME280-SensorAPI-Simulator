"""BME280 calibration data container."""

from dataclasses import dataclass, field


@dataclass
class CalibrationData:
    """
    Factory-programmed NVM trim coefficients used in compensation formulas.

    T1 and P1 are unsigned; all other T/P coefficients are signed.
    H1 and H3 are unsigned bytes; H2, H4, H5 are signed 16-bit; H6 is signed byte.

    t_fine is not a hardware coefficient — it is a computed intermediate value
    set as a side-effect of compensate_temperature() and consumed by
    compensate_pressure() and compensate_humidity().
    """

    # Temperature (3 coefficients)
    dig_T1: int
    dig_T2: int
    dig_T3: int

    # Pressure (9 coefficients)
    dig_P1: int
    dig_P2: int
    dig_P3: int
    dig_P4: int
    dig_P5: int
    dig_P6: int
    dig_P7: int
    dig_P8: int
    dig_P9: int

    # Humidity (6 coefficients)
    dig_H1: int
    dig_H2: int
    dig_H3: int
    dig_H4: int
    dig_H5: int
    dig_H6: int

    # Shared intermediate temperature value — set during temperature compensation
    t_fine: int = field(default=0, repr=False)

    @classmethod
    def typical(cls) -> "CalibrationData":
        """
        Plausible calibration values representative of a real BME280.
        Produces ~25 °C / ~101 kPa / ~50 %RH for the corresponding ADC inputs.
        """
        return cls(
            dig_T1=27504, dig_T2=26435,  dig_T3=-1000,
            dig_P1=36477, dig_P2=-10685, dig_P3=3024,
            dig_P4=2855,  dig_P5=140,    dig_P6=-7,
            dig_P7=15500, dig_P8=-14600, dig_P9=6000,
            dig_H1=75,    dig_H2=370,    dig_H3=0,
            dig_H4=313,   dig_H5=50,     dig_H6=30,
        )
