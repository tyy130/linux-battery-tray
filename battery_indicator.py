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
import time
from typing import Optional, Tuple, Deque

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
gi.require_version('Gdk', '3.0')
from gi.repository import Gtk, GLib, AppIndicator3, Gdk

import config


# CSS for modern UI styling that respects system theme
MENU_CSS = """
.battery-header {
    font-weight: bold;
    font-size: 1.1em;
    padding: 8px 12px;
}
.battery-status {
    padding: 4px 12px;
    font-size: 0.95em;
}
.battery-time {
    padding: 4px 12px;
    font-size: 0.9em;
    opacity: 0.8;
}
.battery-progress {
    min-height: 10px;
    margin: 8px 12px;
    border-radius: 5px;
}
.battery-progress trough {
    min-height: 10px;
    border-radius: 5px;
    background-color: alpha(currentColor, 0.1);
}
.battery-progress progress {
    min-height: 10px;
    border-radius: 5px;
}

/* Power Manager Dialog Styles */
.power-manager-header {
    font-size: 1.4em;
    font-weight: bold;
    padding: 12px;
}
.power-manager-percentage {
    font-size: 3em;
    font-weight: 300;
}
.power-manager-status {
    font-size: 1.1em;
    opacity: 0.8;
}
.power-manager-detail-label {
    opacity: 0.7;
}
.power-manager-detail-value {
    font-weight: 500;
}
.battery-level-bar {
    min-height: 24px;
    border-radius: 12px;
}
.battery-level-bar trough {
    min-height: 24px;
    border-radius: 12px;
    background-color: alpha(currentColor, 0.15);
}
.battery-level-bar progress {
    min-height: 24px;
    border-radius: 12px;
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

        # Smoothing and throttling state
        self.time_history: Deque[float] = collections.deque(maxlen=config.TIME_SMOOTHING_WINDOW)
        self.last_time_type: Optional[str] = None
        self.battery_health_warned: bool = False
        self.update_source_id: Optional[int] = None
        self.current_update_interval: int = config.UPDATE_INTERVAL
        # Icon update damping
        self._last_percentage: Optional[int] = None
        self._last_icon_update: float = 0.0

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

        # Set up periodic updates (uses adaptive interval)
        self._setup_update_timer(self.current_update_interval)

    def _apply_css(self) -> None:
        """Apply CSS styling to the application."""
        css_provider = Gtk.CssProvider()
        css_provider.load_from_data(MENU_CSS.encode())
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            css_provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def _setup_update_timer(self, interval: int) -> None:
        """Set up the GLib timer for periodic updates with an adaptive interval."""
        if self.update_source_id is not None:
            try:
                GLib.source_remove(self.update_source_id)
            except Exception:
                pass
        self.update_source_id = GLib.timeout_add_seconds(interval, self._periodic_update)
        self.current_update_interval = interval

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

    def _build_menu(self) -> Gtk.Menu:
        """
        Build the dropdown menu for the indicator.

        Returns:
            A Gtk.Menu with battery information and controls.
        """
        menu = Gtk.Menu()

        # Battery percentage header
        self.header_item = Gtk.MenuItem()
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.header_label = Gtk.Label(label="---%")
        self.header_label.set_halign(Gtk.Align.START)
        self.header_label.get_style_context().add_class("battery-header")
        header_box.pack_start(self.header_label, False, False, 0)
        self.header_item.add(header_box)
        self.header_item.set_sensitive(False)
        menu.append(self.header_item)

        # Status item with accent color support
        self.status_item = Gtk.MenuItem()
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.status_label = Gtk.Label(label="Unknown")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.get_style_context().add_class("battery-status")
        status_box.pack_start(self.status_label, False, False, 0)
        self.status_item.add(status_box)
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)

        # Progress bar for battery level
        self.progress_item = Gtk.MenuItem()
        progress_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.get_style_context().add_class("battery-progress")
        progress_box.pack_start(self.progress_bar, False, False, 8)
        self.progress_item.add(progress_box)
        self.progress_item.set_sensitive(False)
        menu.append(self.progress_item)

        # Time remaining item
        self.time_item = Gtk.MenuItem()
        time_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.time_label = Gtk.Label(label="Estimating...")
        self.time_label.set_halign(Gtk.Align.START)
        self.time_label.get_style_context().add_class("battery-time")
        time_box.pack_start(self.time_label, False, False, 0)
        self.time_item.add(time_box)
        self.time_item.set_sensitive(False)
        menu.append(self.time_item)

        # Separator
        menu.append(Gtk.SeparatorMenuItem())

        # Quick Settings submenu
        quick_item = Gtk.MenuItem(label="Quick Settings")
        quick_menu = Gtk.Menu()
        quick_item.set_submenu(quick_menu)

        # Battery Saver toggle
        battery_saver_item = Gtk.CheckMenuItem(label="Battery Saver")
        battery_saver_item.connect("toggled", self._on_battery_saver_toggled)
        curr_profile = self._get_power_profile()
        if curr_profile == "power-saver":
            battery_saver_item.set_active(True)
        quick_menu.append(battery_saver_item)

        # Divider
        quick_menu.append(Gtk.SeparatorMenuItem())

        # Power Mode submenu inside quick settings
        mode_item = Gtk.MenuItem(label="Power Mode")
        mode_menu = Gtk.Menu()
        mode_item.set_submenu(mode_menu)
        # add radio profile items
        profiles = ["Performance", "Balanced", "Power Saver"]
        group = None
        current_profile = self._get_power_profile()
        for p in profiles:
            if group is None:
                item = Gtk.RadioMenuItem(label=p)
                group = item
            else:
                item = Gtk.RadioMenuItem(group=group, label=p)
            item.connect("toggled", self._on_power_profile_changed, p)
            if (p == "Performance" and current_profile == "performance") or (p == "Balanced" and current_profile == "balanced") or (p == "Power Saver" and current_profile == "power-saver") or (current_profile is None and p == config.DEFAULT_POWER_MODE):
                item.set_active(True)
            mode_menu.append(item)

        # Customize item
        customize_item = Gtk.MenuItem(label="Customize...")
        customize_item.connect("activate", self._on_customize_profiles)
        mode_menu.append(Gtk.SeparatorMenuItem())
        mode_menu.append(customize_item)

        quick_menu.append(mode_item)
        menu.append(quick_item)

        # Power Manager button (opens our custom dialog)
        power_item = Gtk.MenuItem(label="Power…")
        power_item.connect("activate", self._on_power_settings_clicked)
        menu.append(power_item)

        # Separator before system actions
        menu.append(Gtk.SeparatorMenuItem())

        # About button
        about_item = Gtk.MenuItem(label="About")
        about_item.connect("activate", self._on_about_clicked)
        menu.append(about_item)

        # Quit button
        quit_item = Gtk.MenuItem(label="Quit")
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

    def _check_power_profiles_support(self) -> bool:
        """Return True if powerprofilesctl exists on the system."""
        return shutil.which("powerprofilesctl") is not None

    def _get_power_profile(self) -> Optional[str]:
        """Query the current power profile if supported."""
        if not self._check_power_profiles_support():
            return None
        try:
            r = subprocess.run(["powerprofilesctl", "get"], capture_output=True, text=True, timeout=2)
            return r.stdout.strip()
        except subprocess.SubprocessError:
            return None

    def _set_power_profile(self, profile: str) -> bool:
        """Set the power profile (performance/balanced/power-saver) if supported."""
        if not self._check_power_profiles_support():
            return False
        try:
            subprocess.run(["powerprofilesctl", "set", profile], check=True, timeout=3)
            return True
        except subprocess.SubprocessError:
            return False

    def _apply_preset(self, name: str) -> None:
        """Apply a named preset: set profile and brightness where possible."""
        preset = config.POWER_MODE_PRESETS.get(name)
        if not preset:
            return

        # Try set profile using powerprofilesctl (map names to profile strings)
        mapping = {
            'Performance': 'performance',
            'Balanced': 'balanced',
            'Power Saver': 'power-saver',
        }
        profile = mapping.get(name)
        if profile:
            self._set_power_profile(profile)

        # Optionally set screen brightness via brightnessctl if present
        if shutil.which('brightnessctl') and 'brightness' in preset:
            try:
                # brightnessctl set expects percentage like '50%'
                subprocess.run(['brightnessctl', 'set', f"{int(preset['brightness'])}%"], timeout=2)
            except subprocess.SubprocessError:
                pass

    def _preset_config_path(self) -> str:
        """Get path to local presets file for persistence"""
        cfg_dir = os.path.expanduser('~/.config/battery-indicator')
        os.makedirs(cfg_dir, exist_ok=True)
        return os.path.join(cfg_dir, 'presets.json')

    def _load_presets_from_disk(self) -> None:
        """Load presets from disk if present and merge them into runtime presets."""
        import json
        path = self._preset_config_path()
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if k in config.POWER_MODE_PRESETS:
                                config.POWER_MODE_PRESETS[k].update(v)
        except Exception:
            pass

    def _save_presets_to_disk(self) -> None:
        """Save current presets to the user config directory."""
        import json
        path = self._preset_config_path()
        try:
            with open(path, 'w') as f:
                json.dump(config.POWER_MODE_PRESETS, f, indent=2)
        except Exception:
            pass

    def _on_customize_profiles(self, widget: Gtk.MenuItem) -> None:
        """Open a simple customize dialog to edit the presets."""
        self._load_presets_from_disk()
        dialog = Gtk.Dialog("Customize Power Profiles", None, 0)
        dialog.add_button(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL)
        dialog.add_button(Gtk.STOCK_OK, Gtk.ResponseType.OK)
        dialog.set_default_size(380, 220)

        content = dialog.get_content_area()
        grid = Gtk.Grid(column_spacing=8, row_spacing=8)
        content.add(grid)

        # Profile selector
        profiles = list(config.POWER_MODE_PRESETS.keys())
        cmb = Gtk.ComboBoxText()
        for p in profiles:
            cmb.append_text(p)
        cmb.set_active(0)
        grid.attach(Gtk.Label(label="Profile:"), 0, 0, 1, 1)
        grid.attach(cmb, 1, 0, 1, 1)

        # Brightness slider
        grid.attach(Gtk.Label(label="Brightness:"), 0, 1, 1, 1)
        brightness_adj = Gtk.Adjustment(0, 0, 100, 1, 10, 0)
        brightness_scale = Gtk.Scale(orientation=Gtk.Orientation.HORIZONTAL, adjustment=brightness_adj)
        brightness_scale.set_value(config.POWER_MODE_PRESETS[profiles[0]].get('brightness', 80))
        grid.attach(brightness_scale, 1, 1, 1, 1)

        # Dim on battery toggle
        dim_toggle = Gtk.CheckButton(label="Dim on battery")
        dim_toggle.set_active(config.POWER_MODE_PRESETS[profiles[0]].get('dim_on_battery', True))
        grid.attach(dim_toggle, 0, 2, 2, 1)

        # Dim percent
        grid.attach(Gtk.Label(label="Dim Percent:"), 0, 3, 1, 1)
        dim_adj = Gtk.Adjustment(30, 0, 100, 1, 10, 0)
        dim_spin = Gtk.SpinButton(adjustment=dim_adj)
        dim_spin.set_value(config.POWER_MODE_PRESETS[profiles[0]].get('dim_percent', 60))
        grid.attach(dim_spin, 1, 3, 1, 1)

        # When profile changes, update UI
        def on_profile_changed(cb):
            name = cb.get_active_text()
            if name and name in config.POWER_MODE_PRESETS:
                p = config.POWER_MODE_PRESETS[name]
                brightness_scale.set_value(p.get('brightness', 80))
                dim_toggle.set_active(p.get('dim_on_battery', True))
                dim_spin.set_value(p.get('dim_percent', 60))

        cmb.connect('changed', on_profile_changed)

        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            name = cmb.get_active_text()
            if name:
                config.POWER_MODE_PRESETS[name]['brightness'] = int(brightness_scale.get_value())
                config.POWER_MODE_PRESETS[name]['dim_on_battery'] = bool(dim_toggle.get_active())
                config.POWER_MODE_PRESETS[name]['dim_percent'] = int(dim_spin.get_value())
                self._save_presets_to_disk()
                # apply if active
                current = self._get_power_profile()
                mapping = {'Performance': 'performance', 'Balanced': 'balanced', 'Power Saver': 'power-saver'}
                if mapping.get(name) == current:
                    self._apply_preset(name)

        dialog.destroy()

    def _on_power_profile_changed(self, widget: Gtk.RadioMenuItem, profile: str) -> None:
        """Handle radio menu toggles, applying the named profile if active."""
        if widget.get_active():
            self._apply_preset(profile)

    def _on_battery_saver_toggled(self, widget: Gtk.CheckMenuItem) -> None:
        """Toggle battery saver: sets power-saver profile if active, otherwise revert to default."""
        active = widget.get_active()
        if active:
            self._apply_preset('Power Saver')
        else:
            # restore last known or default
            last = self._get_power_profile()
            if last is None or last == 'power-saver':
                self._apply_preset(config.DEFAULT_POWER_MODE)

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

    def get_time_remaining(self) -> str:
        """
        Get the time remaining estimate using upower.

        Returns:
            A string describing the time remaining, or "Unknown" if unavailable.
        """
        if not self.battery_path:
            return "Unknown"

        # Extract battery name from path (e.g., BAT0 from /sys/class/power_supply/BAT0)
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

            # Try to get time to empty or time to full
            for line in output.split('\n'):
                if 'time to empty' in line.lower():
                    parts = line.split(':', 1)
                    if len(parts) >= 2:
                        time_str = self._format_time_string(parts[1].strip())
                        return (time_str, "remaining")
                elif 'time to full' in line.lower():
                    parts = line.split(':', 1)
                    if len(parts) >= 2:
                        time_str = self._format_time_string(parts[1].strip())
                        return (time_str, "until full")

            # If no time info found, return status
            status = self.get_battery_status()
            if status == "Full":
                return ("Fully Charged", "status")
            return ("Estimating...", "status")

        except (subprocess.SubprocessError, FileNotFoundError):
            return ("Unknown", "status")

    def _format_time_string(self, time_str: str) -> str:
        """
        Convert upower time format to human-readable format.
        Converts '2.5 hours' to '2 hr 30 min', '45 minutes' to '45 min', etc.

        Args:
            time_str: Raw time string from upower.

        Returns:
            Formatted time string.
        """
        time_str = time_str.strip().lower()
        
        # Handle 'X.Y hours' format
        if 'hour' in time_str:
            try:
                # Extract the number
                num = float(time_str.split()[0])
                hours = int(num)
                minutes = int((num - hours) * 60)
                
                if hours > 0 and minutes > 0:
                    return f"{hours} hr {minutes} min"
                elif hours > 0:
                    return f"{hours} hr"
                else:
                    return f"{minutes} min"
            except (ValueError, IndexError):
                return time_str
        
        # Handle 'X.Y minutes' or 'X minutes' format
        elif 'minute' in time_str:
            try:
                num = float(time_str.split()[0])
                return f"{int(num)} min"
            except (ValueError, IndexError):
                return time_str
        
        return time_str

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

        # Health check (only once per session)
        if not self.battery_health_warned:
            health = self.get_battery_health()
            if health is not None and health < config.HEALTH_WARNING_THRESHOLD:
                # Show dialog, and also send a notification
                try:
                    self._show_battery_health_dialog(health)
                except Exception:
                    # Fallback to notification
                    self.send_notification(
                        "Battery Health Warning",
                        f"Battery health is low ({health}%). Consider replacing it.",
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

    def _show_battery_health_dialog(self, health: int) -> None:
        """Show a modal dialog to warn users about degraded battery health."""
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.NONE,
            text=f"Battery Health: {health}%"
        )
        dialog.format_secondary_text(
            "Your battery's maximum capacity has dropped. Consider replacing it to restore expected runtime."
        )
        dialog.add_buttons("Close", Gtk.ResponseType.CLOSE, "More Info", Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                subprocess.Popen(['xdg-open', 'https://en.wikipedia.org/wiki/Lithium-ion_battery#Degradation'])
            except Exception:
                pass
        dialog.destroy()

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

        # Update icon with damping to avoid flicker on fluctuating estimates
        icon_name = self.get_icon_name(percentage, status)
        now_ts = time.time()
        should_update_icon = False
        if self._last_percentage is None:
            should_update_icon = True
        elif percentage is None:
            should_update_icon = True
        else:
            # update only if difference is substantial or enough time passed
            if abs(percentage - (self._last_percentage or 0)) >= 1:
                should_update_icon = True
            if now_ts - self._last_icon_update > 12:
                should_update_icon = True
            # also update if status changed
            if status.lower() != getattr(self, '_last_status', '').lower():
                should_update_icon = True

        if should_update_icon:
            try:
                self.indicator.set_icon(icon_name)
                self._last_percentage = percentage
                self._last_icon_update = now_ts
                self._last_status = status
            except Exception:
                pass

        # Update tooltip with battery status
        tooltip_text = self._get_tooltip_text(percentage, status, time_info)
        self.indicator.set_title(tooltip_text)

        # Update label if configured
        if config.SHOW_PERCENTAGE_LABEL and percentage is not None:
            self.indicator.set_label(f"{percentage}%", "100%")
        else:
            self.indicator.set_label("", "")

        # Update menu items with modern UI
        if percentage is not None:
            self.header_label.set_text(f"{percentage}%")
            self.progress_bar.set_fraction(percentage / 100.0)
        else:
            self.header_label.set_text("Battery Not Detected")
            self.progress_bar.set_fraction(0.0)

        # Update status with accent color for charging
        status_lower = status.lower()
        style_context = self.status_label.get_style_context()
        # Remove previous state classes
        style_context.remove_class("suggested-action")
        style_context.remove_class("destructive-action")

        if status_lower == "charging":
            self.status_label.set_text("Charging")
            style_context.add_class("suggested-action")
        elif status_lower == "discharging":
            self.status_label.set_text("On Battery")
        elif status_lower == "full":
            self.status_label.set_text("Fully Charged")
            style_context.add_class("suggested-action")
        elif status_lower == "not charging":
            self.status_label.set_text("Plugged In")
        else:
            self.status_label.set_text(status)

        # Update time display
        time_display = self._format_time_display(status, time_info)
        self.time_label.set_text(time_display)

        # Check for low battery warnings
        self.check_low_battery(percentage, status)

    def _periodic_update(self) -> bool:
        """
        Periodic update callback.

        Returns:
            True to continue the timeout, False to stop it.
        """
        self.update_battery_info()
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
