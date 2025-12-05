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
/* Card-style menu container */
menu {
    padding: 8px;
}

/* Header Card - battery status */
.card-container {
    background-color: alpha(@theme_bg_color, 0.95);
    border-radius: 12px;
    padding: 16px;
    margin: 4px;
}
.battery-title-row {
    font-size: 1.2em;
    font-weight: 600;
}
.battery-subtitle {
    font-size: 0.95em;
    color: alpha(@theme_fg_color, 0.7);
    margin-top: 4px;
}

/* Battery Level Bar - color coded */
.battery-level-bar {
    min-height: 10px;
    border-radius: 5px;
    margin: 12px 4px 8px 4px;
}
.battery-level-bar trough {
    min-height: 10px;
    border-radius: 5px;
    background-color: alpha(@theme_fg_color, 0.12);
}
.battery-level-bar progress {
    min-height: 10px;
    border-radius: 5px;
    background-color: @theme_selected_bg_color;
}
.battery-level-good progress {
    background-image: linear-gradient(to right, #43a047, #66bb6a);
}
.battery-level-ok progress {
    background-image: linear-gradient(to right, #ef6c00, #ffa726);
}
.battery-level-low progress {
    background-image: linear-gradient(to right, #e53935, #ef5350);
}
.battery-level-critical progress {
    background-image: linear-gradient(to right, #b71c1c, #d32f2f);
}

/* Status colors */
.status-charging {
    color: #42a5f5;
}
.status-full {
    color: #66bb6a;
}
.status-low {
    color: #ffa726;
}
.status-critical {
    color: #ef5350;
}

/* Slider controls */
.slider-row {
    padding: 8px 4px;
}
.slider-label {
    font-size: 0.92em;
    min-width: 80px;
}
.slider-control {
    min-width: 140px;
    min-height: 24px;
}
.slider-control trough {
    min-height: 6px;
    border-radius: 3px;
    background-color: alpha(@theme_fg_color, 0.12);
}
.slider-control highlight {
    min-height: 6px;
    border-radius: 3px;
    background-color: @theme_selected_bg_color;
}
.slider-control slider {
    min-width: 16px;
    min-height: 16px;
    border-radius: 8px;
    background-color: @theme_selected_bg_color;
}
.slider-value {
    font-size: 0.85em;
    min-width: 35px;
    color: alpha(@theme_fg_color, 0.7);
}

/* Info row */
.info-row {
    font-size: 0.88em;
    color: alpha(@theme_fg_color, 0.65);
    padding: 4px 8px;
}

/* Hint text styling */
.hint-text {
    font-style: italic;
    color: alpha(@theme_fg_color, 0.55);
    font-size: 0.88em;
}

/* Menu items with icons */
.menu-item-box {
    padding: 4px 0;
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
        
        # Power profile auto-switching settings
        self.auto_performance_on_ac: bool = False
        self.auto_saver_on_battery: bool = False
        self.offer_saver_on_low: bool = True
        self.saver_offered_this_session: bool = False
        self.last_ac_status: Optional[bool] = None

        # Find custom icons path
        self.icons_path: Optional[str] = self._find_icons_path()

        # Apply CSS styling
        self._apply_css()

        # Create the indicator with custom icon path
        self.indicator = AppIndicator3.Indicator.new(
            "battery-indicator",
            "bat-ind-missing",
            AppIndicator3.IndicatorCategory.HARDWARE
        )
        
        # Set custom icon theme path if available
        if self.icons_path:
            self.indicator.set_icon_theme_path(self.icons_path)
        
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

    def _find_icons_path(self) -> Optional[str]:
        """Find the custom icons directory."""
        # Check various locations for our custom icons
        possible_paths = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons"),
            os.path.join(self.install_dir, "icons"),
            "/usr/share/battery-indicator/icons",
        ]
        for path in possible_paths:
            if os.path.isdir(path):
                return path
        return None

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
        header_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        header_card.set_margin_start(8)
        header_card.set_margin_end(8)
        header_card.set_margin_top(12)
        header_card.set_margin_bottom(8)
        
        # Title row: [icon] Battery at XX%
        title_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        
        # Create header icon - use custom icon if available
        self.header_icon = Gtk.Image()
        self._update_header_icon("bat-ind-100")  # Will be updated by update_battery_info
        title_row.pack_start(self.header_icon, False, False, 0)
        
        self.header_label = Gtk.Label(label="Battery at ---%")
        self.header_label.set_halign(Gtk.Align.START)
        self.header_label.get_style_context().add_class("battery-title-row")
        title_row.pack_start(self.header_label, False, False, 0)
        header_card.pack_start(title_row, False, False, 0)
        
        # Subtitle row: Status — time remaining
        self.subtitle_label = Gtk.Label(label="Checking status...")
        self.subtitle_label.set_halign(Gtk.Align.START)
        self.subtitle_label.set_margin_start(34)  # Align with text after icon
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
        progress_box.set_margin_start(8)
        progress_box.set_margin_end(8)
        
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
        info_box.set_margin_start(8)
        info_box.set_margin_bottom(4)
        
        self.info_label = Gtk.Label(label="")
        self.info_label.set_halign(Gtk.Align.START)
        self.info_label.get_style_context().add_class("info-row")
        info_box.pack_start(self.info_label, False, False, 0)
        
        self.info_item.add(info_box)
        menu.append(self.info_item)

        menu.append(Gtk.SeparatorMenuItem())

        # ═══════════════════════════════════════════════════════════════
        # POWER MODE - With visual indicator of current mode
        # ═══════════════════════════════════════════════════════════════
        mode_item = Gtk.MenuItem()
        mode_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        mode_icon = Gtk.Image.new_from_icon_name("power-profile-balanced-symbolic", Gtk.IconSize.MENU)
        mode_box.pack_start(mode_icon, False, False, 0)
        mode_label = Gtk.Label(label="Power Mode")
        mode_box.pack_start(mode_label, False, False, 0)
        mode_item.add(mode_box)
        
        mode_menu = Gtk.Menu()
        mode_item.set_submenu(mode_menu)
        
        if self._check_power_profiles_support():
            current_profile = self._get_power_profile()
            
            # Performance
            perf_item = Gtk.RadioMenuItem(label="⚡ Performance")
            perf_item.connect("toggled", self._on_power_profile_changed, "performance")
            if current_profile == "performance":
                perf_item.set_active(True)
            mode_menu.append(perf_item)
            
            # Balanced
            bal_item = Gtk.RadioMenuItem(group=perf_item, label="⚖ Balanced")
            bal_item.connect("toggled", self._on_power_profile_changed, "balanced")
            if current_profile == "balanced":
                bal_item.set_active(True)
            mode_menu.append(bal_item)
            
            # Power Saver
            save_item = Gtk.RadioMenuItem(group=perf_item, label="🔋 Power Saver")
            save_item.connect("toggled", self._on_power_profile_changed, "power-saver")
            if current_profile == "power-saver":
                save_item.set_active(True)
            mode_menu.append(save_item)
        else:
            # Hint text instead of gray disabled
            hint_item = Gtk.MenuItem()
            hint_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            hint_icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic", Gtk.IconSize.MENU)
            hint_box.pack_start(hint_icon, False, False, 0)
            hint_label = Gtk.Label(label="Not available")
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

    def _update_header_icon(self, icon_name: str) -> None:
        """Update the header icon in the menu using custom SVG if available."""
        if self.icons_path:
            icon_path = os.path.join(self.icons_path, f"{icon_name}.svg")
            if os.path.exists(icon_path):
                try:
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 24, 24)
                    self.header_icon.set_from_pixbuf(pixbuf)
                    return
                except Exception:
                    pass
        # Fallback to system icon
        self.header_icon.set_from_icon_name("battery-full-symbolic", Gtk.IconSize.LARGE_TOOLBAR)

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
        Uses custom icons if available, falls back to system icons.

        Args:
            percentage: Battery percentage (0-100) or None.
            status: Battery status string.

        Returns:
            Icon name string (custom or system theme).
        """
        if percentage is None:
            return "bat-ind-missing" if self.icons_path else "battery-missing-symbolic"

        is_charging = status.lower() == "charging"
        
        # If we have custom icons, use them (unique names to avoid system icon conflicts)
        if self.icons_path:
            if is_charging:
                return "bat-ind-charging"
            elif percentage >= 80:
                return "bat-ind-100"
            elif percentage >= 60:
                return "bat-ind-80"
            elif percentage >= 40:
                return "bat-ind-60"
            elif percentage >= 20:
                return "bat-ind-40"
            elif percentage > 5:
                return "bat-ind-20"
            else:
                return "bat-ind-empty"
        
        # Fall back to system icons
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
        Also handles automatic power profile switching.

        Args:
            percentage: Current battery percentage.
            status: Current battery status.
        """
        if percentage is None:
            return

        status_lower = status.lower()
        is_on_ac = status_lower in ("charging", "full", "not charging")
        
        # Handle automatic power profile switching
        if self._check_power_profiles_support():
            # Check if AC status changed
            if self.last_ac_status is not None and self.last_ac_status != is_on_ac:
                if is_on_ac and self.auto_performance_on_ac:
                    self._set_power_profile("performance")
                    self.send_notification(
                        "Power Profile Changed",
                        "Switched to Performance mode (plugged in)",
                        "low"
                    )
                elif not is_on_ac and self.auto_saver_on_battery:
                    self._set_power_profile("power-saver")
                    self.send_notification(
                        "Power Profile Changed", 
                        "Switched to Power Saver mode (on battery)",
                        "low"
                    )
            self.last_ac_status = is_on_ac

        # Don't send low battery notifications if charging
        if is_on_ac:
            self.last_notification_level = None
            self.saver_offered_this_session = False
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

        # Low battery warning with power saver offer
        elif percentage <= config.LOW_BATTERY_THRESHOLD:
            if self.last_notification_level != config.LOW_BATTERY_THRESHOLD:
                # Offer to switch to power saver if enabled and not already offered
                if (self.offer_saver_on_low and 
                    not self.saver_offered_this_session and 
                    self._check_power_profiles_support()):
                    current_profile = self._get_power_profile()
                    if current_profile != "power-saver":
                        self.send_notification(
                            "Low Battery",
                            f"Battery at {percentage}%. Switch to Power Saver mode?",
                            "normal"
                        )
                        self.saver_offered_this_session = True
                        # Auto-switch if auto_saver_on_battery is enabled
                        if self.auto_saver_on_battery:
                            self._set_power_profile("power-saver")
                    else:
                        self.send_notification(
                            "Low Battery",
                            f"Battery at {percentage}%. Consider plugging in.",
                            "normal"
                        )
                else:
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
        
        # Update header icon to match battery level (use custom icon)
        self._update_header_icon(icon_name)
        
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
        """Show comprehensive power settings dialog."""
        dialog = Gtk.Dialog(
            title="Power Settings",
            transient_for=None,
            flags=0
        )
        dialog.set_default_size(420, 520)
        dialog.set_resizable(False)
        
        content = dialog.get_content_area()
        content.set_spacing(0)

        # Create notebook for tabs
        notebook = Gtk.Notebook()
        notebook.set_margin_start(12)
        notebook.set_margin_end(12)
        notebook.set_margin_top(12)
        notebook.set_margin_bottom(12)
        content.pack_start(notebook, True, True, 0)

        # ═══════════════════════════════════════════════════════════════
        # TAB 1: Battery Status
        # ═══════════════════════════════════════════════════════════════
        status_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        status_page.set_margin_start(16)
        status_page.set_margin_end(16)
        status_page.set_margin_top(16)
        status_page.set_margin_bottom(16)

        # Battery icon and percentage
        battery_header = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        battery_header.set_halign(Gtk.Align.CENTER)
        
        percentage = getattr(self, '_current_percentage', None)
        status = getattr(self, '_current_status', 'Unknown')
        
        # Use our custom icon
        icon_name = self.get_icon_name(percentage, status)
        if self.icons_path:
            icon_path = os.path.join(self.icons_path, f"{icon_name}.svg")
            if os.path.exists(icon_path):
                try:
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 64, 64)
                    battery_icon = Gtk.Image.new_from_pixbuf(pixbuf)
                except Exception:
                    battery_icon = Gtk.Image.new_from_icon_name("battery-full-symbolic", Gtk.IconSize.DIALOG)
            else:
                battery_icon = Gtk.Image.new_from_icon_name("battery-full-symbolic", Gtk.IconSize.DIALOG)
        else:
            battery_icon = Gtk.Image.new_from_icon_name("battery-full-symbolic", Gtk.IconSize.DIALOG)
        battery_icon.set_pixel_size(64)
        battery_header.pack_start(battery_icon, False, False, 0)

        pct_label = Gtk.Label(label=f"{percentage}%" if percentage else "---%")
        pct_label.get_style_context().add_class("power-manager-percentage")
        battery_header.pack_start(pct_label, False, False, 0)

        status_text = self._get_status_text(status)
        status_label = Gtk.Label(label=status_text)
        status_label.get_style_context().add_class("power-manager-status")
        battery_header.pack_start(status_label, False, False, 0)

        status_page.pack_start(battery_header, False, False, 8)

        # Progress bar
        level_bar = Gtk.ProgressBar()
        if percentage:
            level_bar.set_fraction(percentage / 100.0)
        level_bar.get_style_context().add_class("dialog-level-bar")
        status_page.pack_start(level_bar, False, False, 8)

        # Time remaining
        time_info = getattr(self, '_current_time_info', ('Unknown', 'status'))
        time_str, time_type = time_info
        if time_type in ("remaining", "until full"):
            time_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            time_box.set_halign(Gtk.Align.CENTER)
            time_icon = Gtk.Image.new_from_icon_name("appointment-soon-symbolic", Gtk.IconSize.SMALL_TOOLBAR)
            time_box.pack_start(time_icon, False, False, 0)
            time_text = f"{time_str} remaining" if time_type == "remaining" else f"{time_str} until full"
            time_label = Gtk.Label(label=time_text)
            time_box.pack_start(time_label, False, False, 0)
            status_page.pack_start(time_box, False, False, 4)

        # Separator
        status_page.pack_start(Gtk.Separator(), False, False, 8)

        # Battery details grid
        details_frame = Gtk.Frame(label="Battery Details")
        details_grid = Gtk.Grid()
        details_grid.set_row_spacing(8)
        details_grid.set_column_spacing(24)
        details_grid.set_margin_start(12)
        details_grid.set_margin_end(12)
        details_grid.set_margin_top(8)
        details_grid.set_margin_bottom(8)

        row = 0
        health = self.get_battery_health()
        if health:
            self._add_detail_row(details_grid, row, "Battery Health", f"{health}%")
            row += 1

        energy_now = self._read_battery_file("energy_now")
        if energy_now:
            try:
                energy_wh = int(energy_now) / 1000000
                self._add_detail_row(details_grid, row, "Energy", f"{energy_wh:.1f} Wh")
                row += 1
            except ValueError:
                pass

        power_now = self._read_battery_file("power_now")
        if power_now:
            try:
                power_w = int(power_now) / 1000000
                self._add_detail_row(details_grid, row, "Power Draw", f"{power_w:.1f} W")
                row += 1
            except ValueError:
                pass

        voltage_now = self._read_battery_file("voltage_now")
        if voltage_now:
            try:
                voltage_v = int(voltage_now) / 1000000
                self._add_detail_row(details_grid, row, "Voltage", f"{voltage_v:.2f} V")
                row += 1
            except ValueError:
                pass

        details_frame.add(details_grid)
        status_page.pack_start(details_frame, False, False, 0)

        notebook.append_page(status_page, Gtk.Label(label="Status"))

        # ═══════════════════════════════════════════════════════════════
        # TAB 2: Power Profiles
        # ═══════════════════════════════════════════════════════════════
        profiles_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        profiles_page.set_margin_start(16)
        profiles_page.set_margin_end(16)
        profiles_page.set_margin_top(16)
        profiles_page.set_margin_bottom(16)

        # Current profile section
        profile_frame = Gtk.Frame(label="Power Profile")
        profile_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        profile_box.set_margin_start(12)
        profile_box.set_margin_end(12)
        profile_box.set_margin_top(8)
        profile_box.set_margin_bottom(8)

        if self._check_power_profiles_support():
            current_profile = self._get_power_profile()
            
            # Performance
            perf_radio = Gtk.RadioButton.new_with_label(None, "⚡ Performance")
            perf_radio.set_tooltip_text("Maximum performance, higher power consumption")
            if current_profile == "performance":
                perf_radio.set_active(True)
            perf_radio.connect("toggled", lambda w: self._set_power_profile("performance") if w.get_active() else None)
            profile_box.pack_start(perf_radio, False, False, 4)
            
            # Balanced
            bal_radio = Gtk.RadioButton.new_with_label_from_widget(perf_radio, "⚖ Balanced")
            bal_radio.set_tooltip_text("Balance between performance and power saving")
            if current_profile == "balanced":
                bal_radio.set_active(True)
            bal_radio.connect("toggled", lambda w: self._set_power_profile("balanced") if w.get_active() else None)
            profile_box.pack_start(bal_radio, False, False, 4)
            
            # Power Saver
            saver_radio = Gtk.RadioButton.new_with_label_from_widget(perf_radio, "🔋 Power Saver")
            saver_radio.set_tooltip_text("Maximum battery life, reduced performance")
            if current_profile == "power-saver":
                saver_radio.set_active(True)
            saver_radio.connect("toggled", lambda w: self._set_power_profile("power-saver") if w.get_active() else None)
            profile_box.pack_start(saver_radio, False, False, 4)
        else:
            no_profiles_label = Gtk.Label(label="Power profiles not available.\nInstall power-profiles-daemon to enable.")
            no_profiles_label.set_line_wrap(True)
            profile_box.pack_start(no_profiles_label, False, False, 8)

        profile_frame.add(profile_box)
        profiles_page.pack_start(profile_frame, False, False, 0)

        # Auto-switch settings
        auto_frame = Gtk.Frame(label="Automatic Switching")
        auto_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        auto_box.set_margin_start(12)
        auto_box.set_margin_end(12)
        auto_box.set_margin_top(8)
        auto_box.set_margin_bottom(8)

        # Performance when plugged in
        self.auto_perf_check = Gtk.CheckButton(label="Switch to Performance when plugged in")
        self.auto_perf_check.set_active(getattr(self, 'auto_performance_on_ac', False))
        self.auto_perf_check.connect("toggled", self._on_auto_perf_toggled)
        auto_box.pack_start(self.auto_perf_check, False, False, 4)

        # Power saver when on battery
        self.auto_saver_check = Gtk.CheckButton(label="Switch to Power Saver on battery")
        self.auto_saver_check.set_active(getattr(self, 'auto_saver_on_battery', False))
        self.auto_saver_check.connect("toggled", self._on_auto_saver_toggled)
        auto_box.pack_start(self.auto_saver_check, False, False, 4)

        # Low battery power saver notification
        self.low_battery_saver_check = Gtk.CheckButton(label="Offer Power Saver when battery is low")
        self.low_battery_saver_check.set_active(getattr(self, 'offer_saver_on_low', True))
        self.low_battery_saver_check.connect("toggled", self._on_offer_saver_toggled)
        auto_box.pack_start(self.low_battery_saver_check, False, False, 4)

        auto_frame.add(auto_box)
        profiles_page.pack_start(auto_frame, False, False, 0)

        notebook.append_page(profiles_page, Gtk.Label(label="Profiles"))

        # ═══════════════════════════════════════════════════════════════
        # TAB 3: Notifications
        # ═══════════════════════════════════════════════════════════════
        notif_page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
        notif_page.set_margin_start(16)
        notif_page.set_margin_end(16)
        notif_page.set_margin_top(16)
        notif_page.set_margin_bottom(16)

        notif_frame = Gtk.Frame(label="Battery Notifications")
        notif_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        notif_box.set_margin_start(12)
        notif_box.set_margin_end(12)
        notif_box.set_margin_top(8)
        notif_box.set_margin_bottom(8)

        # Low battery warning
        low_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        low_label = Gtk.Label(label="Low battery warning at:")
        low_box.pack_start(low_label, False, False, 0)
        low_spin = Gtk.SpinButton.new_with_range(5, 50, 5)
        low_spin.set_value(config.LOW_BATTERY_THRESHOLD)
        low_label_pct = Gtk.Label(label="%")
        low_box.pack_start(low_spin, False, False, 0)
        low_box.pack_start(low_label_pct, False, False, 0)
        notif_box.pack_start(low_box, False, False, 4)

        # Critical battery warning
        crit_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        crit_label = Gtk.Label(label="Critical battery warning at:")
        crit_box.pack_start(crit_label, False, False, 0)
        crit_spin = Gtk.SpinButton.new_with_range(3, 20, 1)
        crit_spin.set_value(config.CRITICAL_BATTERY_THRESHOLD)
        crit_label_pct = Gtk.Label(label="%")
        crit_box.pack_start(crit_spin, False, False, 0)
        crit_box.pack_start(crit_label_pct, False, False, 0)
        notif_box.pack_start(crit_box, False, False, 4)

        notif_frame.add(notif_box)
        notif_page.pack_start(notif_frame, False, False, 0)

        # Health notifications
        health_frame = Gtk.Frame(label="Health Notifications")
        health_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        health_box.set_margin_start(12)
        health_box.set_margin_end(12)
        health_box.set_margin_top(8)
        health_box.set_margin_bottom(8)

        health_check = Gtk.CheckButton(label="Warn when battery health is below 40%")
        health_check.set_active(True)
        health_box.pack_start(health_check, False, False, 4)

        health_frame.add(health_box)
        notif_page.pack_start(health_frame, False, False, 0)

        notebook.append_page(notif_page, Gtk.Label(label="Notifications"))

        # ═══════════════════════════════════════════════════════════════
        # Bottom buttons
        # ═══════════════════════════════════════════════════════════════
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        button_box.set_halign(Gtk.Align.END)
        button_box.set_margin_start(12)
        button_box.set_margin_end(12)
        button_box.set_margin_bottom(12)

        system_btn = Gtk.Button(label="System Settings")
        system_btn.connect("clicked", self._on_system_settings_clicked)
        button_box.pack_start(system_btn, False, False, 0)

        close_btn = Gtk.Button(label="Close")
        close_btn.connect("clicked", lambda w: dialog.destroy())
        button_box.pack_start(close_btn, False, False, 0)

        content.pack_start(button_box, False, False, 0)

        dialog.show_all()

    def _on_auto_perf_toggled(self, widget: Gtk.CheckButton) -> None:
        """Handle auto performance toggle."""
        self.auto_performance_on_ac = widget.get_active()

    def _on_auto_saver_toggled(self, widget: Gtk.CheckButton) -> None:
        """Handle auto saver toggle."""
        self.auto_saver_on_battery = widget.get_active()

    def _on_offer_saver_toggled(self, widget: Gtk.CheckButton) -> None:
        """Handle offer saver toggle."""
        self.offer_saver_on_low = widget.get_active()

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
        about.set_version("1.1.0")
        about.set_comments("A lightweight system tray battery indicator for Linux.")
        about.set_website("https://github.com/tyy130/linux-battery-tray")
        about.set_authors(["TacticDev", "Tyler Hill"])
        about.set_copyright("© 2025 TacticDev")
        
        # Use our custom icon if available
        if self.icons_path:
            icon_path = os.path.join(self.icons_path, "bat-ind-100.svg")
            if os.path.exists(icon_path):
                try:
                    from gi.repository import GdkPixbuf
                    pixbuf = GdkPixbuf.Pixbuf.new_from_file_at_size(icon_path, 64, 64)
                    about.set_logo(pixbuf)
                except Exception:
                    about.set_logo_icon_name("battery-full-symbolic")
            else:
                about.set_logo_icon_name("battery-full-symbolic")
        else:
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
