"""
Configuration options for the Linux Battery Tray Indicator.

This module contains all configurable settings for the battery indicator
application. Modify these values to customize the behavior.
"""

# Update interval in seconds (how often to refresh battery status)
UPDATE_INTERVAL: int = 30

# Battery threshold percentages for notifications
LOW_BATTERY_THRESHOLD: int = 15  # Show warning notification at this level
CRITICAL_BATTERY_THRESHOLD: int = 5  # Show critical notification at this level

# Display options
SHOW_PERCENTAGE_LABEL: bool = True  # Show percentage text next to tray icon

# Icon level thresholds
BATTERY_FULL_THRESHOLD: int = 80  # >= this = full icon
BATTERY_GOOD_THRESHOLD: int = 50  # >= this = good icon
BATTERY_LOW_THRESHOLD: int = 20  # >= this = low icon
BATTERY_CAUTION_THRESHOLD: int = 10  # >= this = caution icon
# Below caution threshold = empty icon

# Battery paths (will try these in order)
BATTERY_PATHS: list = [
    "/sys/class/power_supply/BAT0",
    "/sys/class/power_supply/BAT1",
]

# Smoothing/behavior options
# How many samples to keep for time smoothing
TIME_SMOOTHING_WINDOW: int = 5

# At or below this health percentage, warn the user
HEALTH_WARNING_THRESHOLD: int = 40

# Update interval (seconds) when low battery
LOW_BATTERY_UPDATE_INTERVAL: int = 10

# Power mode presets - a simple, adjustable mapping of modes to settings
# Each mode can define brightness (0-100), dim_on_battery (bool), dim_percent (0-100)
POWER_MODE_PRESETS = {
    "Performance": {
        "brightness": 100,
        "dim_on_battery": False,
        "dim_percent": 100,
    },
    "Balanced": {
        "brightness": 80,
        "dim_on_battery": True,
        "dim_percent": 60,
    },
    "Power Saver": {
        "brightness": 40,
        "dim_on_battery": True,
        "dim_percent": 30,
    }
}

# Default power mode to show
DEFAULT_POWER_MODE: str = "Balanced"

