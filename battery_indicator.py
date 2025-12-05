#!/usr/bin/env python3
"""
Linux Battery Tray Indicator

A lightweight system tray battery indicator for Linux using GTK3 and AppIndicator3.
Displays battery percentage, charging status, and time remaining estimates.
"""

import subprocess
import os
import sys
import shutil
import collections
from typing import Optional, Tuple, Deque

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, GLib, AppIndicator3, Gdk

import config


# CSS for modern dashboard-style UI
MENU_CSS = """
/* Header Card */
.battery-card {
    padding: 12px 16px;
}
.battery-title-row {
    font-size: 1.15em;
    font-weight: 600;
}
.battery-subtitle {
    font-size: 0.92em;
    color: alpha(@theme_fg_color, 0.75);
    margin-top: 2px;
}

/* Battery Level Bar */
.battery-level-bar {
    min-height: 8px;
    border-radius: 4px;
    margin: 8px 0;
}
.battery-level-bar trough {
    min-height: 8px;
    border-radius: 4px;
    background-color: alpha(@theme_fg_color, 0.15);
}
.battery-level-bar progress {
    min-height: 8px;
    border-radius: 4px;
    background-color: @theme_selected_bg_color;
}
.battery-level-good progress {
    background-color: #4caf50;
}
.battery-level-ok progress {
    background-color: #ff9800;
}
.battery-level-low progress {
    background-color: #f44336;
}
.battery-level-critical progress {
    background-color: #d32f2f;
}

/* Status colors */
.status-charging {
    color: #42a5f5;
}
.status-full {
    color: #66bb6a;
}
.status-low {
    color: #ff9800;
}
.status-critical {
    color: #f44336;
}

/* Slider controls */
.control-row {
    padding: 6px 16px;
}
.control-label {
    font-size: 0.9em;
    min-width: 90px;
}
.control-slider {
    min-width: 120px;
}
.control-slider trough {
    min-height: 6px;
    border-radius: 3px;
    background-color: alpha(@theme_fg_color, 0.15);
}
.control-slider highlight {
    min-height: 6px;
    border-radius: 3px;
}
.control-slider slider {
    min-width: 14px;
    min-height: 14px;
    border-radius: 7px;
}

/* Menu section styling */
.menu-section-label {
    font-size: 0.8em;
    font-weight: 600;
    color: alpha(@theme_fg_color, 0.6);
    padding: 8px 16px 4px 16px;
}

/* Hint text (instead of grayed disabled) */
.hint-text {
    font-style: italic;
    color: alpha(@theme_fg_color, 0.6);
    font-size: 0.85em;
}

/* Power mode indicator */
.mode-active {
    font-weight: 600;
}

/* Extra info row */
.info-row {
    font-size: 0.85em;
    color: alpha(@theme_fg_color, 0.7);
    padding: 4px 16px;
}

/* Power Manager Dialog Styles */
.power-manager-percentage {
    font-size: 3em;
    font-weight: 300;
}
.power-manager-status {
    font-size: 1.1em;
}
.power-manager-detail-label {
    font-weight: normal;
}
.power-manager-detail-value {
    font-weight: 600;
}
.dialog-level-bar {
    min-height: 20px;
    border-radius: 10px;
}
.dialog-level-bar trough {
    min-height: 20px;
    border-radius: 10px;
    background-color: alpha(@theme_fg_color, 0.15);
}
.dialog-level-bar progress {
    min-height: 20px;
    border-radius: 10px;
}
"""


class BatteryIndicator:
    """
    System tray battery indicator that displays battery status and provides
    a menu with detailed information.
    """

    def __init__(self) -> None:
        """Initialize the battery indicator."""
        self.battery_path: Optional[str] = self._find_battery_path()
        self.last_notification_level: Optional[int] = None
        self.install_dir: str = "/opt/battery-indicator"
        
        # State for time smoothing and adaptive updates
        self.time_history: Deque[float] = collections.deque(maxlen=5)
        self.last_time_type: Optional[str] = None
        self.battery_health_warned: bool = False
        self.update_source_id: Optional[int] = None
        self.current_update_interval: int = config.UPDATE_INTERVAL

        # Apply CSS styling
        self._apply_css()

        # Create the indicator
        self.indicator = AppIndicator3.Indicator.new(
            "battery-indicator",
            "battery-missing-symbolic",
            AppIndicator3.IndicatorCategory.HARDWARE
        )
        self.indicator.set_status(AppIndicator3.IndicatorStatus.ACTIVE)

        # Build the menu
        self.menu = self._build_menu()
        self.indicator.set_menu(self.menu)

        # Initial update
        self.update_battery_info()

        # Set up periodic updates
        self._setup_update_timer(self.current_update_interval)

    def _setup_update_timer(self, interval: int) -> None:
        """Set up the update timer with the specified interval."""
        if self.update_source_id is not None:
            GLib.source_remove(self.update_source_id)
        self.update_source_id = GLib.timeout_add_seconds(interval, self._periodic_update)
        self.current_update_interval = interval

    def _apply_css(self) -> None:
        """Apply CSS styling to the application."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(MENU_CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _find_battery_path(self) -> Optional[str]:
        """
        Find the battery path from the configured paths.

        Returns:
            The path to the battery directory, or None if no battery is found.
        """
        for path in config.BATTERY_PATHS:
            if os.path.exists(path):
                return path
        return None

    def _check_power_profiles_support(self) -> bool:
        """Check if power-profiles-daemon is available."""
        return shutil.which("powerprofilesctl") is not None

    def _get_power_profile(self) -> Optional[str]:
        """Get the current power profile."""
        if not self._check_power_profiles_support():
            return None
        try:
            result = subprocess.run(
                ["powerprofilesctl", "get"],
                capture_output=True,
                text=True,
                timeout=2
            )
            return result.stdout.strip()
        except subprocess.SubprocessError:
            return None

    def _set_power_profile(self, profile: str) -> None:
        """Set the power profile."""
        if not self._check_power_profiles_support():
            return
        try:
            subprocess.run(
                ["powerprofilesctl", "set", profile],
                capture_output=True,
                timeout=2
            )
        except subprocess.SubprocessError:
            pass

    def _on_power_profile_changed(self, widget: Gtk.RadioMenuItem, profile: str) -> None:
        """Handle power profile change."""
        if widget.get_active():
            self._set_power_profile(profile)

    def _get_brightness_path(self) -> Optional[str]:
        """Find the backlight brightness path."""
        backlight_base = "/sys/class/backlight"
        if os.path.exists(backlight_base):
            for name in os.listdir(backlight_base):
                path = os.path.join(backlight_base, name)
                if os.path.exists(os.path.join(path, "brightness")):
                    return path
        return None

    def _get_brightness(self) -> Optional[Tuple[int, int]]:
        """Get current brightness and max brightness."""
        path = self._get_brightness_path()
        if not path:
            return None
        try:
            with open(os.path.join(path, "brightness")) as f:
                current = int(f.read().strip())
            with open(os.path.join(path, "max_brightness")) as f:
                max_val = int(f.read().strip())
            return (current, max_val)
        except (IOError, ValueError):
            return None

    def _set_brightness(self, value: int) -> None:
        """Set brightness value."""
        path = self._get_brightness_path()
        if not path:
            return
        try:
            # Use pkexec or brightnessctl if available
            if shutil.which("brightnessctl"):
                subprocess.run(["brightnessctl", "set", str(value)], 
                             capture_output=True, timeout=2)
            else:
                # Direct write (may need permissions)
                with open(os.path.join(path, "brightness"), "w") as f:
                    f.write(str(value))
        except (IOError, subprocess.SubprocessError):
            pass

    def _on_brightness_changed(self, scale: Gtk.Scale) -> None:
        """Handle brightness slider change."""
        value = int(scale.get_value())
        self._set_brightness(value)

    def _build_menu(self) -> Gtk.Menu:
        """
        Build the dropdown menu for the indicator.
        Dashboard-style card UI with status, controls, and actions.
        """
        menu = Gtk.Menu()

        # ═══════════════════════════════════════════════════════════════
        # HEADER CARD - Battery status with icon
        # ═══════════════════════════════════════════════════════════════
        self.header_item = Gtk.MenuItem()
        self.header_item.set_sensitive(False)
        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        header_card.set_margin_start(4)
        header_card.set_margin_end(4)
        header_card.set_margin_top(8)
        header_card.set_margin_bottom(4)
        
        # Title row: [icon] Battery at XX%
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.header_icon = Gtk.Image.new_from_icon_name("battery-full-symbolic", Gtk.IconSize.MENU)
        title_row.pack_start(self.header_icon, False, False, 0)
        
        self.header_label = Gtk.Label(label="Battery at ---%")
        self.header_label.set_halign(Gtk.Align.START)
        self.header_label.get_style_context().add_class("battery-title-row")
        title_row.pack_start(self.header_label, False, False, 0)
        header_card.pack_start(title_row, False, False, 0)
        
        # Subtitle row: Status — time remaining
        self.subtitle_label = Gtk.Label(label="Checking status...")
        self.subtitle_label.set_halign(Gtk.Align.START)
        self.subtitle_label.set_margin_start(24)  # Align with text after icon
        self.subtitle_label.get_style_context().add_class("battery-subtitle")
        header_card.pack_start(self.subtitle_label, False, False, 0)
        
        self.header_item.add(header_card)
        menu.append(self.header_item)

        # ═══════════════════════════════════════════════════════════════
        # BATTERY LEVEL BAR - Color-coded progress
        # ═══════════════════════════════════════════════════════════════
        self.progress_item = Gtk.MenuItem()
        self.progress_item.set_sensitive(False)
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        progress_box.set_margin_start(4)
        progress_box.set_margin_end(4)
        
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.get_style_context().add_class("battery-level-bar")
        progress_box.pack_start(self.progress_bar, False, False, 4)
        
        self.progress_item.add(progress_box)
        menu.append(self.progress_item)

        # ═══════════════════════════════════════════════════════════════
        # EXTRA INFO ROW - Battery health or power draw
        # ═══════════════════════════════════════════════════════════════
        self.info_item = Gtk.MenuItem()
        self.info_item.set_sensitive(False)
        info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        info_box.set_margin_start(4)
        
        self.info_label = Gtk.Label(label="")
        self.info_label.set_halign(Gtk.Align.START)
        self.info_label.get_style_context().add_class("info-row")
        info_box.pack_start(self.info_label, False, False, 0)
        
        self.info_item.add(info_box)
        menu.append(self.info_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ═══════════════════════════════════════════════════════════════
        # CONTROLS SECTION - Brightness slider
        # ═══════════════════════════════════════════════════════════════
        brightness_info = self._get_brightness()
        if brightness_info:
            current_brightness, max_brightness = brightness_info
            
            brightness_item = Gtk.MenuItem()
            brightness_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            brightness_box.set_margin_start(4)
            brightness_box.set_margin_end(4)
            
            # Sun icon
            sun_icon = Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.MENU)
            brightness_box.pack_start(sun_icon, False, False, 0)
            
            # Label
            brightness_label = Gtk.Label(label="Brightness")
            brightness_label.set_halign(Gtk.Align.START)
            brightness_label.get_style_context().add_class("control-label")
            brightness_box.pack_start(brightness_label, False, False, 0)
            
            # Slider
            self.brightness_scale = Gtk.Scale.new_with_range(
                Gtk.Orientation.HORIZONTAL, 
                1, max_brightness, max_brightness / 100
            )
            self.brightness_scale.set_value(current_brightness)
            self.brightness_scale.set_draw_value(False)
            self.brightness_scale.set_size_request(120, -1)
            self.brightness_scale.get_style_context().add_class("control-slider")
            self.brightness_scale.connect("value-changed", self._on_brightness_changed)
            brightness_box.pack_end(self.brightness_scale, False, False, 0)
            
            brightness_item.add(brightness_box)
            # Keep the item sensitive so slider works
            menu.append(brightness_item)
            
            menu.append(Gtk.SeparatorMenuItem())

        # ═══════════════════════════════════════════════════════════════
        # POWER MODE - With visual indicator of current mode
        # ═══════════════════════════════════════════════════════════════
        mode_item = Gtk.MenuItem(label="Power Mode")
        mode_menu = Gtk.Menu()
        mode_item.set_submenu(mode_menu)
        
        if self._check_power_profiles_support():
            current_profile = self._get_power_profile()
            
            # Performance
            perf_item = Gtk.RadioMenuItem(label="⚡ Performance")
            perf_item.connect("toggled", self._on_power_profile_changed, "performance")
            if current_profile == "performance":
                perf_item.set_active(True)
                perf_item.get_style_context().add_class("mode-active")
            mode_menu.append(perf_item)
            
            # Balanced
            bal_item = Gtk.RadioMenuItem(group=perf_item, label="⚖ Balanced")
            bal_item.connect("toggled", self._on_power_profile_changed, "balanced")
            if current_profile == "balanced":
                bal_item.set_active(True)
                bal_item.get_style_context().add_class("mode-active")
            mode_menu.append(bal_item)
            
            # Power Saver
            save_item = Gtk.RadioMenuItem(group=perf_item, label="🔋 Power Saver")
            save_item.connect("toggled", self._on_power_profile_changed, "power-saver")
            if current_profile == "power-saver":
                save_item.set_active(True)
                save_item.get_style_context().add_class("mode-active")
            mode_menu.append(save_item)
        else:
            # Hint text instead of gray disabled
            hint_item = Gtk.MenuItem()
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.MENU)
            hint_box.pack_start(hint_icon, False, False, 0)
            hint_label = Gtk.Label(label="Install power-profiles-daemon")
            hint_label.get_style_context().add_class("hint-text")
            hint_box.pack_start(hint_label, False, False, 0)
            hint_item.add(hint_box)
            hint_item.set_sensitive(False)
            mode_menu.append(hint_item)
        
        menu.append(mode_item)

        # Power Settings
        power_item = Gtk.MenuItem()
        power_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        power_icon = Gtk.Image.new_from_icon_name("preferences-system-power-symbolic", Gtk.IconSize.MENU)
        power_box.pack_start(power_icon, False, False, 0)
        power_label = Gtk.Label(label="Power Settings")
        power_box.pack_start(power_label, False, False, 0)
        power_item.add(power_box)
        power_item.connect("activate", self._on_power_settings_clicked)
        menu.append(power_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ═══════════════════════════════════════════════════════════════
        # ACTIONS SECTION
        # ═══════════════════════════════════════════════════════════════
        # About
        about_item = Gtk.MenuItem()
        about_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        about_icon = Gtk.Image.new_from_icon_name("help-about-symbolic", Gtk.IconSize.MENU)
        about_box.pack_start(about_icon, False, False, 0)
        about_label = Gtk.Label(label="About")
        about_box.pack_start(about_label, False, False, 0)
        about_item.add(about_box)
        about_item.connect("activate", self._on_about_clicked)
        menu.append(about_item)

        # Quit
        quit_item = Gtk.MenuItem()
        quit_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        quit_icon = Gtk.Image.new_from_icon_name("application-exit-symbolic", Gtk.IconSize.MENU)
        quit_box.pack_start(quit_icon, False, False, 0)
        quit_label = Gtk.Label(label="Quit")
        quit_box.pack_start(quit_label, False, False, 0)
        quit_item.add(quit_box)
        quit_item.connect("activate", self._on_quit_clicked)
        menu.append(quit_item)

        menu.show_all()
        return menu

    def _read_battery_file(self, filename: str) -> Optional[str]:
        """
        Read a file from the battery sysfs directory.

        Args:
            filename: The name of the file to read.

        Returns:
            The contents of the file stripped of whitespace, or None on error.
        """
        if not self.battery_path:
            return None

        filepath = os.path.join(self.battery_path, filename)
        try:
            with open(filepath, 'r') as f:
                return f.read().strip()
        except (IOError, OSError):
            return None

    def get_battery_percentage(self) -> Optional[int]:
        """
        Get the current battery percentage.

        Returns:
            Battery percentage as an integer, or None if unavailable.
        """
        capacity = self._read_battery_file("capacity")
        if capacity is not None:
            try:
                return int(capacity)
            except ValueError:
                pass
        return None

    def get_battery_status(self) -> str:
        """
        Get the current battery charging status.

        Returns:
            Status string (Charging, Discharging, Full, Not charging, or Unknown).
        """
        status = self._read_battery_file("status")
        return status if status else "Unknown"

    def _parse_upower_time_to_minutes(self, time_str: str) -> float:
        """Parse upower time string to minutes."""
        parts = time_str.strip().split()
        if len(parts) < 2:
            return 0.0
        try:
            val = float(parts[0])
            unit = parts[1].lower()
            if 'hour' in unit:
                return val * 60
            elif 'minute' in unit:
                return val
            return 0.0
        except ValueError:
            return 0.0

    def get_time_remaining(self) -> Tuple[str, str]:
        """
        Get the time remaining estimate using upower with smoothing.

        Returns:
            A tuple of (time_string, time_type).
        """
        if not self.battery_path:
            return ("Unknown", "status")

        battery_name = os.path.basename(self.battery_path)
        upower_device = f"/org/freedesktop/UPower/devices/battery_{battery_name}"

        try:
            result = subprocess.run(
                ["upower", "-i", upower_device],
                capture_output=True,
                text=True,
                timeout=5
            )
            output = result.stdout

            current_time_type = None
            raw_time_str = None

            for line in output.split('\n'):
                if 'time to empty' in line.lower():
                    current_time_type = "remaining"
                    raw_time_str = line.split(':', 1)[1].strip()
                    break
                elif 'time to full' in line.lower():
                    current_time_type = "until full"
                    raw_time_str = line.split(':', 1)[1].strip()
                    break

            if current_time_type and raw_time_str:
                # If time type changed (e.g. plugged in), reset history
                if current_time_type != self.last_time_type:
                    self.time_history.clear()
                    self.last_time_type = current_time_type

                # Parse and smooth
                minutes = self._parse_upower_time_to_minutes(raw_time_str)
                if minutes > 0:
                    self.time_history.append(minutes)
                    
                    # Calculate average for smoothing
                    avg_minutes = sum(self.time_history) / len(self.time_history)
                    
                    # Format to string
                    hours = int(avg_minutes / 60)
                    mins = int(avg_minutes % 60)
                    
                    if hours > 0:
                        time_str = f"{hours} hr {mins} min"
                    else:
                        time_str = f"{mins} min"
                        
                    return (time_str, current_time_type)

            status = self.get_battery_status()
            if status == "Full":
                return ("Fully Charged", "status")
            return ("Estimating...", "status")

        except (subprocess.SubprocessError, FileNotFoundError):
            return ("Unknown", "status")

    def get_icon_name(self, percentage: Optional[int], status: str) -> str:
        """
        Determine the appropriate icon name based on battery level and status.

        Args:
            percentage: Battery percentage (0-100) or None.
            status: Battery status string.

        Returns:
            Icon name string for the system theme (using -symbolic suffix for
            better system integration and animated icons).
        """
        if percentage is None:
            return "battery-missing-symbolic"

        is_charging = status.lower() == "charging"
        suffix = "-charging-symbolic" if is_charging else "-symbolic"

        if percentage >= config.BATTERY_FULL_THRESHOLD:
            return f"battery-full{suffix}"
        elif percentage >= config.BATTERY_GOOD_THRESHOLD:
            return f"battery-good{suffix}"
        elif percentage >= config.BATTERY_LOW_THRESHOLD:
            return f"battery-low{suffix}"
        elif percentage >= config.BATTERY_CAUTION_THRESHOLD:
            return f"battery-caution{suffix}"
        else:
            return "battery-empty-symbolic"

    def send_notification(self, title: str, message: str, urgency: str = "normal") -> None:
        """
        Send a desktop notification using notify-send.

        Args:
            title: Notification title.
            message: Notification body text.
            urgency: Notification urgency (low, normal, critical).
        """
        try:
            subprocess.run(
                ["notify-send", "-u", urgency, "-i", "battery-low", title, message],
                timeout=5
            )
        except (subprocess.SubprocessError, FileNotFoundError):
            pass  # Silently fail if notify-send is not available

    def get_battery_health(self) -> Optional[int]:
        """Calculate battery health percentage."""
        energy_full = self._read_battery_file("energy_full")
        energy_full_design = self._read_battery_file("energy_full_design")
        
        if not energy_full or not energy_full_design:
            # Try charge_* if energy_* not available
            energy_full = self._read_battery_file("charge_full")
            energy_full_design = self._read_battery_file("charge_full_design")

        if energy_full and energy_full_design:
            try:
                return int(int(energy_full) / int(energy_full_design) * 100)
            except (ValueError, ZeroDivisionError):
                pass
        return None

    def check_low_battery(self, percentage: Optional[int], status: str) -> None:
        """
        Check if battery is low and send notifications as needed.

        Args:
            percentage: Current battery percentage.
            status: Current battery status.
        """
        if percentage is None:
            return

        # Don't notify if charging
        if status.lower() in ("charging", "full"):
            self.last_notification_level = None
            return

        # Critical battery warning
        if percentage <= config.CRITICAL_BATTERY_THRESHOLD:
            if self.last_notification_level != config.CRITICAL_BATTERY_THRESHOLD:
                self.send_notification(
                    "Critical Battery Level",
                    f"Battery at {percentage}%! Connect charger immediately.",
                    "critical"
                )
                self.last_notification_level = config.CRITICAL_BATTERY_THRESHOLD

        # Low battery warning
        elif percentage <= config.LOW_BATTERY_THRESHOLD:
            if self.last_notification_level != config.LOW_BATTERY_THRESHOLD:
                self.send_notification(
                    "Low Battery",
                    f"Battery at {percentage}%. Consider plugging in.",
                    "normal"
                )
                self.last_notification_level = config.LOW_BATTERY_THRESHOLD

        else:
            self.last_notification_level = None

        # Battery health check (only once per session)
        if not self.battery_health_warned:
            health = self.get_battery_health()
            if health is not None and health < 40:
                self.send_notification(
                    "Battery Health Warning",
                    f"Your battery health is low ({health}%). Consider replacing it soon.",
                    "normal"
                )
                self.battery_health_warned = True

    def _get_tooltip_text(self, percentage: Optional[int], status: str, time_info: Tuple[str, str]) -> str:
        """
        Generate tooltip text for the tray icon.

        Args:
            percentage: Battery percentage (0-100) or None.
            status: Battery status string.
            time_info: Tuple of (time_string, time_type).

        Returns:
            Tooltip text describing the current battery status.
        """
        if percentage is None:
            return "Battery Not Detected"

        time_str, time_type = time_info
        status_lower = status.lower()

        if status_lower == "charging":
            if time_type == "until full":
                return f"{time_str} Until Full ({percentage}%)"
            else:
                return f"Charging ({percentage}%)"
        elif status_lower == "discharging":
            if time_type == "remaining":
                return f"{time_str} Remaining ({percentage}%)"
            else:
                return f"{percentage}% Remaining"
        elif status_lower == "full":
            return "Fully Charged"
        elif status_lower == "not charging":
            return f"Not Charging ({percentage}%)"
        else:
            return f"Battery {percentage}%"

    def _format_time_display(self, status: str, time_info: Tuple[str, str]) -> str:
        """
        Format the time remaining for display in the menu.

        Args:
            status: Battery status string.
            time_info: Tuple of (time_string, time_type).

        Returns:
            Formatted time string for display.
        """
        time_str, time_type = time_info
        status_lower = status.lower()

        if status_lower == "charging":
            if time_type == "until full":
                return f"{time_str} until full"
            else:
                return "Estimating..."
        elif status_lower == "discharging":
            if time_type == "remaining":
                return f"{time_str} remaining"
            else:
                return "Estimating..."
        elif status_lower == "full":
            return "Fully Charged"
        elif status_lower == "not charging":
            return "Plugged in, not charging"
        else:
            return time_str

    def update_battery_info(self) -> None:
        """Update all battery information and refresh the UI."""
        # Get current battery info
        percentage = self.get_battery_percentage()
        status = self.get_battery_status()
        time_info = self.get_time_remaining()

        # Store for power manager dialog
        self._current_percentage = percentage
        self._current_status = status
        self._current_time_info = time_info

        # Update tray icon (use set_icon_full to avoid deprecation warning)
        icon_name = self.get_icon_name(percentage, status)
        self.indicator.set_icon_full(icon_name, "Battery Status")

        # Update tooltip with battery status
        tooltip_text = self._get_tooltip_text(percentage, status, time_info)
        self.indicator.set_title(tooltip_text)

        # Update label if configured
        if config.SHOW_PERCENTAGE_LABEL and percentage is not None:
            self.indicator.set_label(f"{percentage}%", "100%")
        else:
            self.indicator.set_label("", "")

        # ═══════════════════════════════════════════════════════════════
        # UPDATE HEADER CARD
        # ═══════════════════════════════════════════════════════════════
        status_lower = status.lower()
        
        # Update header icon to match battery level
        self.header_icon.set_from_icon_name(icon_name, Gtk.IconSize.MENU)
        
        # Update header label: "Battery at XX%"
        if percentage is not None:
            self.header_label.set_text(f"Battery at {percentage}%")
        else:
            self.header_label.set_text("Battery Not Detected")
        
        # Update subtitle: "Status — time remaining"
        time_str, time_type = time_info
        if percentage is not None:
            if status_lower == "charging":
                status_text = "Charging"
                if time_type == "until full":
                    subtitle = f"{status_text} — {time_str} until full"
                else:
                    subtitle = f"{status_text} — estimating..."
            elif status_lower == "discharging":
                status_text = "On battery"
                if time_type == "remaining":
                    subtitle = f"{status_text} — {time_str} remaining"
                else:
                    subtitle = f"{status_text} — estimating..."
            elif status_lower == "full":
                subtitle = "Fully charged"
            elif status_lower == "not charging":
                subtitle = "Plugged in, not charging"
            else:
                subtitle = status
        else:
            subtitle = "No battery detected"
        
        self.subtitle_label.set_text(subtitle)
        
        # Apply status color to header
        header_style = self.header_label.get_style_context()
        for cls in ["status-charging", "status-full", "status-low", "status-critical"]:
            header_style.remove_class(cls)
        
        if status_lower == "charging":
            header_style.add_class("status-charging")
        elif status_lower == "full":
            header_style.add_class("status-full")
        elif percentage is not None and percentage <= config.CRITICAL_BATTERY_THRESHOLD:
            header_style.add_class("status-critical")
        elif percentage is not None and percentage <= config.LOW_BATTERY_THRESHOLD:
            header_style.add_class("status-low")

        # ═══════════════════════════════════════════════════════════════
        # UPDATE BATTERY LEVEL BAR - Color-coded
        # ═══════════════════════════════════════════════════════════════
        if percentage is not None:
            self.progress_bar.set_fraction(percentage / 100.0)
        else:
            self.progress_bar.set_fraction(0.0)
        
        # Apply color class based on level
        bar_style = self.progress_bar.get_style_context()
        for cls in ["battery-level-good", "battery-level-ok", "battery-level-low", "battery-level-critical"]:
            bar_style.remove_class(cls)
        
        if percentage is not None:
            if percentage >= 50:
                bar_style.add_class("battery-level-good")
            elif percentage >= 30:
                bar_style.add_class("battery-level-ok")
            elif percentage >= config.CRITICAL_BATTERY_THRESHOLD:
                bar_style.add_class("battery-level-low")
            else:
                bar_style.add_class("battery-level-critical")

        # ═══════════════════════════════════════════════════════════════
        # UPDATE INFO ROW - Show health or power draw
        # ═══════════════════════════════════════════════════════════════
        health = self.get_battery_health()
        power_now = self._read_battery_file("power_now")
        
        info_parts = []
        if health is not None:
            if health >= 80:
                health_text = f"Health: {health}% (Good)"
            elif health >= 50:
                health_text = f"Health: {health}% (Fair)"
            else:
                health_text = f"Health: {health}% (Poor)"
            info_parts.append(health_text)
        
        if power_now:
            try:
                power_w = int(power_now) / 1000000
                info_parts.append(f"Power: {power_w:.1f} W")
            except ValueError:
                pass
        
        if info_parts:
            self.info_label.set_text("  •  ".join(info_parts))
            self.info_item.show()
        else:
            self.info_item.hide()

        # Check for low battery warnings
        self.check_low_battery(percentage, status)

    def _periodic_update(self) -> bool:
        """
        Periodic update callback with adaptive interval.

        Returns:
            True to continue the timeout, False to stop it.
        """
        self.update_battery_info()
        
        # Adaptive update interval - more frequent when battery is low
        percentage = self.get_battery_percentage()
        if percentage is not None:
            new_interval = config.UPDATE_INTERVAL
            if percentage < 20:
                new_interval = 10  # Update every 10s when below 20%
            
            if new_interval != self.current_update_interval:
                self._setup_update_timer(new_interval)
                return False  # Stop this timer, new one started
                
        return True  # Continue the timeout

    def _on_refresh_clicked(self, widget: Gtk.MenuItem) -> None:
        """Handle refresh button click."""
        self.update_battery_info()

    def _detect_desktop_environment(self) -> str:
        """
        Detect the current desktop environment.

        Returns:
            Desktop environment name (gnome, kde, xfce, or unknown).
        """
        desktop = os.environ.get('XDG_CURRENT_DESKTOP', '').lower()
        session = os.environ.get('DESKTOP_SESSION', '').lower()

        if 'gnome' in desktop or 'gnome' in session or 'unity' in desktop:
            return 'gnome'
        elif 'kde' in desktop or 'plasma' in desktop or 'kde' in session:
            return 'kde'
        elif 'xfce' in desktop or 'xfce' in session:
            return 'xfce'
        elif 'cinnamon' in desktop or 'cinnamon' in session:
            return 'cinnamon'
        elif 'mate' in desktop or 'mate' in session:
            return 'mate'
        else:
            return 'unknown'

    def _on_power_settings_clicked(self, widget: Gtk.MenuItem) -> None:
        """Handle power settings button click - opens our power manager dialog."""
        self._show_power_manager()

    def _show_power_manager(self) -> None:
        """Show the power manager dialog with detailed battery information."""
        # Create the dialog window
        dialog = Gtk.Dialog(
            title="Power",
            transient_for=None,
            flags=0
        )
        dialog.set_default_size(380, 420)
        dialog.set_resizable(False)
        
        # Get the content area
        content = dialog.get_content_area()
        content.set_spacing(0)
        content.set_margin_start(24)
        content.set_margin_end(24)
        content.set_margin_top(20)
        content.set_margin_bottom(20)

        # Main container
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content.pack_start(main_box, True, True, 0)

        # Battery icon and percentage section
        battery_section = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        battery_section.set_halign(Gtk.Align.CENTER)
        
        # Large battery icon
        percentage = getattr(self, '_current_percentage', None)
        status = getattr(self, '_current_status', 'Unknown')
        icon_name = self.get_icon_name(percentage, status)
        battery_icon = Gtk.Image.new_from_icon_name(icon_name, Gtk.IconSize.DIALOG)
        battery_icon.set_pixel_size(64)
        battery_section.pack_start(battery_icon, False, False, 0)

        # Large percentage text
        if percentage is not None:
            pct_label = Gtk.Label(label=f"{percentage}%")
        else:
            pct_label = Gtk.Label(label="---%")
        pct_label.get_style_context().add_class("power-manager-percentage")
        battery_section.pack_start(pct_label, False, False, 0)

        # Status text
        status_text = self._get_status_text(status)
        status_label = Gtk.Label(label=status_text)
        status_label.get_style_context().add_class("power-manager-status")
        battery_section.pack_start(status_label, False, False, 0)

        main_box.pack_start(battery_section, False, False, 8)

        # Large progress bar
        level_bar = Gtk.ProgressBar()
        if percentage is not None:
            level_bar.set_fraction(percentage / 100.0)
        level_bar.get_style_context().add_class("battery-level-bar")
        main_box.pack_start(level_bar, False, False, 8)

        # Time remaining section
        time_info = getattr(self, '_current_time_info', ('Unknown', 'status'))
        time_str, time_type = time_info
        
        if time_type in ("remaining", "until full"):
            time_section = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            time_section.set_halign(Gtk.Align.CENTER)
            
            time_icon = Gtk.Image.new_from_icon_name("appointment-soon-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
            time_section.pack_start(time_icon, False, False, 0)
            
            if time_type == "remaining":
                time_text = f"{time_str} remaining"
            else:
                time_text = f"{time_str} until full"
            
            time_label = Gtk.Label(label=time_text)
            time_section.pack_start(time_label, False, False, 0)
            main_box.pack_start(time_section, False, False, 4)

        # Separator
        separator = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        separator.set_margin_top(8)
        separator.set_margin_bottom(8)
        main_box.pack_start(separator, False, False, 0)

        # Details section
        details_grid = Gtk.Grid()
        details_grid.set_row_spacing(8)
        details_grid.set_column_spacing(16)
        details_grid.set_halign(Gtk.Align.CENTER)

        row = 0
        
        # Battery health/energy info from sysfs
        energy_full = self._read_battery_file("energy_full")
        energy_full_design = self._read_battery_file("energy_full_design")
        energy_now = self._read_battery_file("energy_now")
        power_now = self._read_battery_file("power_now")
        voltage_now = self._read_battery_file("voltage_now")
        
        if energy_full and energy_full_design:
            try:
                health = int(int(energy_full) / int(energy_full_design) * 100)
                self._add_detail_row(details_grid, row, "Battery Health", f"{health}%")
                row += 1
            except (ValueError, ZeroDivisionError):
                pass

        if energy_now:
            try:
                energy_wh = int(energy_now) / 1000000
                self._add_detail_row(details_grid, row, "Energy", f"{energy_wh:.1f} Wh")
                row += 1
            except ValueError:
                pass

        if power_now:
            try:
                power_w = int(power_now) / 1000000
                self._add_detail_row(details_grid, row, "Power Draw", f"{power_w:.1f} W")
                row += 1
            except ValueError:
                pass

        if voltage_now:
            try:
                voltage_v = int(voltage_now) / 1000000
                self._add_detail_row(details_grid, row, "Voltage", f"{voltage_v:.2f} V")
                row += 1
            except ValueError:
                pass

        main_box.pack_start(details_grid, False, False, 0)

        # Button box
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(16)

        # System Settings button
        settings_btn = Gtk.Button(label="System Settings")
        settings_btn.connect("clicked", self._on_system_settings_clicked)
        button_box.pack_start(settings_btn, False, False, 0)

        # Close button
        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda w: dialog.destroy())
        button_box.pack_start(close_btn, False, False, 0)

        main_box.pack_start(button_box, False, False, 0)

        dialog.show_all()

    def _add_detail_row(self, grid: Gtk.Grid, row: int, label: str, value: str) -> None:
        """Add a detail row to the grid."""
        label_widget = Gtk.Label(label=label)
        label_widget.set_halign(Gtk.Align.END)
        label_widget.get_style_context().add_class("power-manager-detail-label")
        grid.attach(label_widget, 0, row, 1, 1)

        value_widget = Gtk.Label(label=value)
        value_widget.set_halign(Gtk.Align.START)
        value_widget.get_style_context().add_class("power-manager-detail-value")
        grid.attach(value_widget, 1, row, 1, 1)

    def _get_status_text(self, status: str) -> str:
        """Get human-readable status text."""
        status_lower = status.lower()
        if status_lower == "charging":
            return "Charging"
        elif status_lower == "discharging":
            return "On Battery Power"
        elif status_lower == "full":
            return "Fully Charged"
        elif status_lower == "not charging":
            return "Plugged In, Not Charging"
        else:
            return status

    def _on_system_settings_clicked(self, widget: Gtk.Button) -> None:
        """Open system power settings."""
        desktop = self._detect_desktop_environment()

        commands = {
            'gnome': ['gnome-control-center', 'power'],
            'kde': ['systemsettings', 'kcm_powerdevilprofilesconfig'],
            'xfce': ['xfce4-power-manager-settings'],
            'cinnamon': ['cinnamon-settings', 'power'],
            'mate': ['mate-power-preferences'],
        }

        fallbacks = [
            ['gnome-control-center', 'power'],
            ['systemsettings', 'kcm_powerdevilprofilesconfig'],
            ['xfce4-power-manager-settings'],
            ['cinnamon-settings', 'power'],
            ['mate-power-preferences'],
        ]

        if desktop in commands:
            try:
                subprocess.Popen(commands[desktop], start_new_session=True)
                return
            except (FileNotFoundError, OSError):
                pass

        for cmd in fallbacks:
            try:
                subprocess.Popen(cmd, start_new_session=True)
                return
            except (FileNotFoundError, OSError):
                continue

        self.send_notification(
            "Power Settings",
            "Could not open system power settings.",
            "normal"
        )

    def _on_about_clicked(self, widget: Gtk.MenuItem) -> None:
        """Handle about button click."""
        about = Gtk.AboutDialog()
        about.set_program_name("Battery Indicator")
        about.set_version("1.0.0")
        about.set_comments("A lightweight system tray battery indicator for Linux.")
        about.set_website("https://github.com/tyy130/linux-battery-tray")
        about.set_authors(["tyy130"])
        about.set_logo_icon_name("battery-full-symbolic")
        about.set_license_type(Gtk.License.MIT_X11)
        about.run()
        about.destroy()

    def _on_quit_clicked(self, widget: Gtk.MenuItem) -> None:
        """Handle quit button click."""
        Gtk.main_quit()


def main() -> None:
    """Main entry point for the battery indicator application."""
    # Check if running on a system with a display
    if not os.environ.get('DISPLAY') and not os.environ.get('WAYLAND_DISPLAY'):
        print("Error: No display server found. This application requires X11 or Wayland.")
        sys.exit(1)

    try:
        indicator = BatteryIndicator()
        Gtk.main()
    except KeyboardInterrupt:
        print("\nExiting...")
        sys.exit(0)


if __name__ == "__main__":
    main()
