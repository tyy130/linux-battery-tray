#!/usr/bin/env python3
"""
Linux Battery Tray Indicator

A lightweight system tray battery indicator for Linux using GTK3 and AppIndicator3.
Displays battery percentage, charging status, and time remaining estimates.
"""

import subprocess
import os
import sys
from typing import Optional, Tuple

import gi
gi.require_version('Gtk', '3.0')
gi.require_version('AppIndicator3', '0.1')
from gi.repository import Gtk, GLib, AppIndicator3

import config


class BatteryIndicator:
    """
    System tray battery indicator that displays battery status and provides
    a menu with detailed information.
    """

    def __init__(self) -> None:
        """Initialize the battery indicator."""
        self.battery_path: Optional[str] = self._find_battery_path()
        self.last_notification_level: Optional[int] = None

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
        GLib.timeout_add_seconds(config.UPDATE_INTERVAL, self._periodic_update)

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

        # Battery percentage item
        self.percentage_item = Gtk.MenuItem(label="Battery: ---%")
        self.percentage_item.set_sensitive(False)
        menu.append(self.percentage_item)

        # Status item
        self.status_item = Gtk.MenuItem(label="Status: Unknown")
        self.status_item.set_sensitive(False)
        menu.append(self.status_item)

        # Time remaining item
        self.time_item = Gtk.MenuItem(label="Time: Unknown")
        self.time_item.set_sensitive(False)
        menu.append(self.time_item)

        # Separator
        menu.append(Gtk.SeparatorMenuItem())

        # Refresh button
        refresh_item = Gtk.MenuItem(label="Refresh")
        refresh_item.connect("activate", self._on_refresh_clicked)
        menu.append(refresh_item)

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
                    parts = line.split(':')
                    if len(parts) >= 2:
                        return f"{parts[1].strip()} remaining"
                elif 'time to full' in line.lower():
                    parts = line.split(':')
                    if len(parts) >= 2:
                        return f"{parts[1].strip()} to full"

            # If no time info found, return status
            status = self.get_battery_status()
            if status == "Full":
                return "Fully charged"
            return "Calculating..."

        except (subprocess.SubprocessError, FileNotFoundError):
            return "Unknown"

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

    def _get_tooltip_text(self, percentage: Optional[int], status: str, time_remaining: str) -> str:
        """
        Generate tooltip text for the tray icon.

        Args:
            percentage: Battery percentage (0-100) or None.
            status: Battery status string.
            time_remaining: Time remaining string.

        Returns:
            Tooltip text describing the current battery status.
        """
        if percentage is None:
            return "Battery not detected"

        # Build a descriptive tooltip based on status
        if status.lower() == "charging":
            if "to full" in time_remaining.lower():
                return f"Charging - {time_remaining}"
            elif "calculating" in time_remaining.lower():
                return f"Charging - {percentage}%"
            else:
                return f"Charging - {percentage}% ({time_remaining})"
        elif status.lower() == "discharging":
            if "remaining" in time_remaining.lower():
                return f"Discharging - {time_remaining}"
            elif "calculating" in time_remaining.lower():
                return f"On battery - {percentage}%"
            else:
                return f"On battery - {percentage}% ({time_remaining})"
        elif status.lower() == "full":
            return "Fully charged"
        elif status.lower() == "not charging":
            return f"Not charging - {percentage}%"
        else:
            return f"Battery: {percentage}%"

    def update_battery_info(self) -> None:
        """Update all battery information and refresh the UI."""
        # Get current battery info
        percentage = self.get_battery_percentage()
        status = self.get_battery_status()
        time_remaining = self.get_time_remaining()

        # Update icon
        icon_name = self.get_icon_name(percentage, status)
        self.indicator.set_icon(icon_name)

        # Update tooltip with battery status
        tooltip_text = self._get_tooltip_text(percentage, status, time_remaining)
        self.indicator.set_title(tooltip_text)

        # Update label if configured
        if config.SHOW_PERCENTAGE_LABEL and percentage is not None:
            self.indicator.set_label(f"{percentage}%", "100%")
        else:
            self.indicator.set_label("", "")

        # Update menu items
        if percentage is not None:
            self.percentage_item.set_label(f"Battery: {percentage}%")
        else:
            self.percentage_item.set_label("Battery: Not detected")

        self.status_item.set_label(f"Status: {status}")
        self.time_item.set_label(f"Time: {time_remaining}")

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
