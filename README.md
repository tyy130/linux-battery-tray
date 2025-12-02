# Linux Battery Tray Indicator

A lightweight, reliable system tray battery indicator for Linux using Python and GTK3.

![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.6%2B-blue.svg)
![GTK](https://img.shields.io/badge/GTK-3.0-green.svg)

## Features

- **Real-time battery percentage display** in the system tray
- **Dynamic icons** that change based on battery level and charging status
- **Charging/discharging status detection** with visual indicators
- **Low battery warnings** via desktop notifications (at 15% and 5%)
- **Time remaining estimates** using upower
- **Click-to-expand menu** with detailed battery information
- **Lightweight and minimal resource usage**
- **Works on GNOME, KDE, XFCE, and other DEs** with system tray support

## Screenshots

<!-- Add screenshots here -->
*Screenshots coming soon*

## Icon States

| Battery Level | Normal Icon | Charging Icon |
|---------------|-------------|---------------|
| ≥80% (Full) | `battery-full` | `battery-full-charging` |
| ≥50% (Good) | `battery-good` | `battery-good-charging` |
| ≥20% (Low) | `battery-low` | `battery-low-charging` |
| ≥10% (Caution) | `battery-caution` | `battery-caution-charging` |
| <10% (Empty) | `battery-empty` | - |
| No Battery | `battery-missing` | - |

## Installation

### Quick Install (Recommended)

```bash
git clone https://github.com/yourusername/linux-battery-tray.git
cd linux-battery-tray
chmod +x install.sh
./install.sh
```

### Ubuntu/Debian

```bash
# Install dependencies
sudo apt update
sudo apt install python3 python3-gi gir1.2-appindicator3-0.1 gir1.2-gtk-3.0 upower libnotify-bin

# Clone and install
git clone https://github.com/yourusername/linux-battery-tray.git
cd linux-battery-tray
./install.sh
```

### Fedora/RHEL

```bash
# Install dependencies
sudo dnf install python3 python3-gobject libappindicator-gtk3 gtk3 upower libnotify

# Clone and install
git clone https://github.com/yourusername/linux-battery-tray.git
cd linux-battery-tray
./install.sh
```

### Arch Linux

```bash
# Install dependencies
sudo pacman -S python python-gobject libappindicator-gtk3 gtk3 upower libnotify

# Clone and install
git clone https://github.com/yourusername/linux-battery-tray.git
cd linux-battery-tray
./install.sh
```

### Manual Installation

1. Install the required dependencies for your distribution (see above)
2. Copy `battery_indicator.py` and `config.py` to a directory of your choice
3. Make the main script executable: `chmod +x battery_indicator.py`
4. Run: `python3 battery_indicator.py`

## Usage

### Starting the Indicator

After installation, you can start the battery indicator by:

1. **From terminal:** Run `battery-indicator`
2. **From application menu:** Search for "Battery Indicator"
3. **Automatic:** The indicator starts automatically on login (if autostart is enabled)

### Menu Options

Click on the tray icon to see:

- **Battery percentage** - Current battery level
- **Status** - Charging, Discharging, Full, or Not charging
- **Time remaining** - Estimated time to empty or to full charge
- **Refresh** - Manually update battery information
- **Quit** - Close the application

## Configuration

Edit `config.py` to customize the behavior:

```python
# Update interval in seconds (how often to refresh battery status)
UPDATE_INTERVAL = 30

# Battery threshold percentages for notifications
LOW_BATTERY_THRESHOLD = 15      # Show warning notification at this level
CRITICAL_BATTERY_THRESHOLD = 5  # Show critical notification at this level

# Display options
SHOW_PERCENTAGE_LABEL = True    # Show percentage text next to tray icon

# Icon level thresholds
BATTERY_FULL_THRESHOLD = 80     # >= this = full icon
BATTERY_GOOD_THRESHOLD = 50     # >= this = good icon
BATTERY_LOW_THRESHOLD = 20      # >= this = low icon
BATTERY_CAUTION_THRESHOLD = 10  # >= this = caution icon
```

## Troubleshooting

### Battery Not Detected

1. Check if your battery is recognized by the system:
   ```bash
   ls /sys/class/power_supply/
   ```

2. If your battery is named differently (not BAT0 or BAT1), edit `config.py`:
   ```python
   BATTERY_PATHS = [
       "/sys/class/power_supply/YOUR_BATTERY_NAME",
   ]
   ```

### Icon Not Showing in System Tray

- **GNOME:** Install the [AppIndicator extension](https://extensions.gnome.org/extension/615/appindicator-support/)
- **KDE:** AppIndicator support is built-in
- **XFCE:** Ensure the indicator plugin is added to your panel

### Notifications Not Working

Ensure `libnotify-bin` (Debian/Ubuntu) or `libnotify` (Fedora/Arch) is installed:
```bash
# Test notifications
notify-send "Test" "This is a test notification"
```

### Permission Errors

Ensure you have read access to the battery sysfs files:
```bash
cat /sys/class/power_supply/BAT0/capacity
cat /sys/class/power_supply/BAT0/status
```

### Time Remaining Shows "Unknown"

Ensure `upower` is installed and running:
```bash
upower -i /org/freedesktop/UPower/devices/battery_BAT0
```

## Uninstallation

```bash
./install.sh --uninstall
```

Or manually remove:
```bash
sudo rm -rf /opt/battery-indicator
sudo rm /usr/share/applications/battery-indicator.desktop
rm ~/.config/autostart/battery-indicator.desktop
sudo rm /usr/local/bin/battery-indicator
```

## Requirements

- Python 3.6+
- GTK 3.0
- AppIndicator3
- upower
- libnotify

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.

1. Fork the repository
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- GTK and GNOME projects for the excellent toolkit
- The Linux community for inspiration and feedback