"""BME280 register addresses, bitmasks, and mode constants."""

# Register addresses
REG_CHIP_ID   = 0xD0
REG_RESET     = 0xE0
REG_CTRL_HUM  = 0xF2
REG_STATUS    = 0xF3
REG_CTRL_MEAS = 0xF4
REG_CONFIG    = 0xF5
REG_DATA      = 0xF7  # burst start: 0xF7..0xFE (8 bytes)

# Fixed hardware values
CHIP_ID        = 0x60
SOFT_RESET_CMD = 0xB6

# Power modes (mode[1:0] in ctrl_meas)
POWERMODE_SLEEP  = 0x00
POWERMODE_FORCED = 0x01
POWERMODE_NORMAL = 0x03

# Bitmasks and bit positions
SENSOR_MODE_MSK = 0x03
CTRL_HUM_MSK    = 0x07
CTRL_PRESS_MSK  = 0x1C
CTRL_PRESS_POS  = 2
CTRL_TEMP_MSK   = 0xE0
CTRL_TEMP_POS   = 5
FILTER_MSK      = 0x1C
FILTER_POS      = 2
STANDBY_MSK     = 0xE0
STANDBY_POS     = 5

# Status bits
STATUS_MEASURING = 0x08
STATUS_IM_UPDATE = 0x01

# Measurement delay formula constants (µs) — mirrors bme280_cal_meas_delay()
MEAS_OFFSET_US     = 1250
MEAS_DUR_US        = 2300
PRES_HUM_OFFSET_US = 575
