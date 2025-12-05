# Linux Battery Tray Indicator - AI Coding Agent Instructions

## Project Overview
This is a lightweight Linux system tray battery indicator written in Python using GTK3 and AppIndicator3. It provides real-time battery status, notifications, and detailed information via a dropdown menu.

## Architecture & Core Components
- **Main Application (`battery_indicator.py`)**:
  - `BatteryIndicator` class: Manages the tray icon, menu, and update loop.
  - Uses `gi.repository` (Gtk, AppIndicator3, GLib) for the UI and event loop.
  - Reads battery stats directly from `/sys/class/power_supply/BAT*` (Linux sysfs).
  - Uses `upower` for time remaining estimates (via `subprocess`).
  - Uses `notify-send` for desktop notifications.
- **Configuration (`config.py`)**:
  - Centralized settings for update intervals, thresholds, and paths.
  - Constants like `UPDATE_INTERVAL`, `LOW_BATTERY_THRESHOLD`.
- **Installation (`install.sh`)**:
  - Bash script for dependency management (apt, dnf, pacman) and file deployment.
  - Installs to `/opt/battery-indicator`.

## Critical Workflows
- **Running Locally (Dev Mode)**:
  - Run directly: `python3 battery_indicator.py`
  - Ensure dependencies are installed: `sudo apt install python3-gi gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 upower libnotify-bin`
- **Installation**:
  - Run `./install.sh` to install dependencies and copy files to `/opt`.
  - Creates a desktop entry for autostart.
- **Debugging**:
  - Check terminal output when running manually.
  - Verify battery paths in `config.py` if status is not detected.

## Code Patterns & Conventions
- **UI Styling**:
  - Uses CSS provider (`MENU_CSS` in `battery_indicator.py`) for menu styling.
  - Uses system symbolic icons (`battery-full-symbolic`, etc.) for desktop integration.
- **Battery Reading**:
  - Reads raw values from `/sys/class/power_supply/BATx/` (e.g., `capacity`, `status`, `energy_now`).
  - Handles missing files gracefully (returns `None`).
- **Concurrency**:
  - Uses `GLib.timeout_add_seconds` for the main update loop (no threading).
  - Keep the update function lightweight to avoid freezing the UI.

## External Dependencies
- **System Libraries**: GTK3, AppIndicator3, GObject Introspection.
- **System Tools**: `upower` (for time estimates), `notify-send` (libnotify).
- **Python Packages**: `PyGObject` (python3-gi).

## Key Files
- `battery_indicator.py`: Main logic and UI construction.
- `config.py`: Configuration constants.
- `install.sh`: Deployment and dependency logic.
- `packaging/`: Scripts to build a Debian package and DEBIAN metadata (control, postinst), including `build_deb.sh`.

### Notes
- New config items: `TIME_SMOOTHING_WINDOW`, `HEALTH_WARNING_THRESHOLD`, `LOW_BATTERY_UPDATE_INTERVAL`, and `POWER_MODE_PRESETS` are added to `config.py` for customizing smoothing and power mode behavior.
- Quick Settings (Battery Saver toggle and Power Mode presets) rely on `powerprofilesctl` where available. Brightness adjustments use `brightnessctl` when present.
- Editable presets are saved to `~/.config/battery-indicator/presets.json` and loaded at runtime.
