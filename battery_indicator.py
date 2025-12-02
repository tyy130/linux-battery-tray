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
}
.battery-time {
    padding: 4px 12px;
    font-size: 0.9em;
}
.battery-progress {
    min-height: 8px;
    margin: 8px 12px;
    border-radius: 4px;
}
.battery-progress trough {
    min-height: 8px;
    border-radius: 4px;
}
.battery-progress progress {
    min-height: 8px;
    border-radius: 4px;
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
        GLib.timeout_add_seconds(config.UPDATE_INTERVAL, self._periodic_update)

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

    def _build_menu(self) -> Gtk.Menu:
        """
        Build the dropdown menu for the indicator.

        Returns:
            A Gtk.Menu with battery information and controls.
        """
        menu = Gtk.Menu()

        # Battery percentage header (e.g., "Battery is at 77%")
        self.header_item = Gtk.MenuItem()
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.header_label = Gtk.Label(label="Battery is at ---%")
        self.header_label.set_halign(Gtk.Align.START)
        self.header_label.get_style_context().add_class("battery-header")
        header_box.pack_start(self.header_label, False, False, 0)
        self.header_item.add(header_box)
        self.header_item.set_sensitive(False)
        menu.append(self.header_item)

        # Status item with accent color support
        self.status_item = Gtk.MenuItem()
        status_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.status_label = Gtk.Label(label="Status: Unknown")
        self.status_label.set_halign(Gtk.Align.START)
        self.status_label.get_style_context().add_class("battery-status")
        # Use suggested-action class for accent color on charging status
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
        self.time_label = Gtk.Label(label="Calculating...")
        self.time_label.set_halign(Gtk.Align.START)
        self.time_label.get_style_context().add_class("battery-time")
        time_box.pack_start(self.time_label, False, False, 0)
        self.time_item.add(time_box)
        self.time_item.set_sensitive(False)
        menu.append(self.time_item)

        # Separator
        menu.append(Gtk.SeparatorMenuItem())

        # Power Settings button
        power_settings_item = Gtk.MenuItem(label="Power Settings")
        power_settings_item.connect("activate", self._on_power_settings_clicked)
        menu.append(power_settings_item)

        # Refresh button
        refresh_item = Gtk.MenuItem(label="Refresh")
        refresh_item.connect("activate", self._on_refresh_clicked)
        menu.append(refresh_item)

        # Separator before system actions
        menu.append(Gtk.SeparatorMenuItem())

        # Uninstall button
        uninstall_item = Gtk.MenuItem(label="Uninstall")
        uninstall_item.connect("activate", self._on_uninstall_clicked)
        menu.append(uninstall_item)

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

    def _format_time_display(self, status: str, time_remaining: str) -> str:
        """
        Format the time remaining for display in the menu.

        Args:
            status: Battery status string.
            time_remaining: Raw time remaining string.

        Returns:
            Formatted time string for display.
        """
        status_lower = status.lower()
        if status_lower == "charging":
            if "to full" in time_remaining.lower():
                return f"Charging - {time_remaining}"
            elif "calculating" in time_remaining.lower():
                return "Charging - Calculating time..."
            else:
                return f"Charging - {time_remaining}"
        elif status_lower == "discharging":
            if "remaining" in time_remaining.lower():
                return time_remaining
            elif "calculating" in time_remaining.lower():
                return "Calculating time remaining..."
            else:
                return time_remaining
        elif status_lower == "full":
            return "Fully charged"
        elif status_lower == "not charging":
            return "Not charging"
        else:
            return time_remaining

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

        # Update menu items with modern UI
        if percentage is not None:
            self.header_label.set_text(f"Battery is at {percentage}%")
            self.progress_bar.set_fraction(percentage / 100.0)
        else:
            self.header_label.set_text("Battery not detected")
            self.progress_bar.set_fraction(0.0)

        # Update status with accent color for charging
        status_lower = status.lower()
        style_context = self.status_label.get_style_context()
        # Remove previous state classes
        style_context.remove_class("suggested-action")
        style_context.remove_class("destructive-action")

        if status_lower == "charging":
            self.status_label.set_text("Charging")
            # Add accent color class for charging status
            style_context.add_class("suggested-action")
        elif status_lower == "discharging":
            self.status_label.set_text("On Battery")
        elif status_lower == "full":
            self.status_label.set_text("Fully Charged")
            style_context.add_class("suggested-action")
        elif status_lower == "not charging":
            self.status_label.set_text("Not Charging")
        else:
            self.status_label.set_text(status)

        # Update time display
        time_display = self._format_time_display(status, time_remaining)
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
        """Handle power settings button click - opens system power settings."""
        desktop = self._detect_desktop_environment()

        # Desktop-specific power settings commands
        commands = {
            'gnome': ['gnome-control-center', 'power'],
            'kde': ['systemsettings', 'kcm_powerdevilprofilesconfig'],
            'xfce': ['xfce4-power-manager-settings'],
            'cinnamon': ['cinnamon-settings', 'power'],
            'mate': ['mate-power-preferences'],
        }

        # Fallback commands to try
        fallbacks = [
            ['gnome-control-center', 'power'],
            ['systemsettings', 'kcm_powerdevilprofilesconfig'],
            ['xfce4-power-manager-settings'],
            ['cinnamon-settings', 'power'],
            ['mate-power-preferences'],
        ]

        # Try desktop-specific command first
        if desktop in commands:
            try:
                subprocess.Popen(commands[desktop], start_new_session=True)
                return
            except (FileNotFoundError, OSError):
                pass

        # Try fallback commands
        for cmd in fallbacks:
            try:
                subprocess.Popen(cmd, start_new_session=True)
                return
            except (FileNotFoundError, OSError):
                continue

        # If all else fails, show an error notification
        self.send_notification(
            "Power Settings",
            "Could not open power settings. Please open it manually from your system settings.",
            "normal"
        )

    def _on_uninstall_clicked(self, widget: Gtk.MenuItem) -> None:
        """Handle uninstall button click - shows confirmation and uninstalls."""
        # Create confirmation dialog
        dialog = Gtk.MessageDialog(
            transient_for=None,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Uninstall Battery Indicator?"
        )
        dialog.format_secondary_text(
            "This will remove the Battery Indicator application from your system. "
            "You can reinstall it later by running the install script again."
        )

        response = dialog.run()
        dialog.destroy()

        if response == Gtk.ResponseType.YES:
            self._perform_uninstall()

    def _perform_uninstall(self) -> None:
        """Perform the actual uninstallation."""
        # Validate install directory to prevent accidental deletion of system files
        # Only allow uninstall from the expected installation directory
        expected_install_dir = "/opt/battery-indicator"
        if self.install_dir != expected_install_dir:
            self.send_notification(
                "Uninstall Error",
                "Invalid installation directory. Please uninstall manually.",
                "normal"
            )
            return

        # Show progress notification
        self.send_notification(
            "Uninstalling",
            "Removing Battery Indicator...",
            "normal"
        )

        # Uninstall commands with explicit paths (not user-configurable)
        uninstall_commands = [
            ['sudo', 'rm', '-rf', expected_install_dir],
            ['sudo', 'rm', '-f', '/usr/share/applications/battery-indicator.desktop'],
            ['rm', '-f', os.path.expanduser('~/.config/autostart/battery-indicator.desktop')],
            ['sudo', 'rm', '-f', '/usr/local/bin/battery-indicator'],
        ]

        success = True
        for cmd in uninstall_commands:
            try:
                result = subprocess.run(cmd, capture_output=True, timeout=30)
                if result.returncode != 0 and 'sudo' in cmd:
                    # Try with pkexec for graphical sudo
                    pkexec_cmd = ['pkexec'] + cmd[1:]  # Remove sudo, add pkexec
                    pkexec_result = subprocess.run(pkexec_cmd, capture_output=True, timeout=30)
                    if pkexec_result.returncode != 0:
                        success = False
            except (subprocess.SubprocessError, FileNotFoundError):
                success = False

        if success:
            self.send_notification(
                "Uninstall Complete",
                "Battery Indicator has been removed. The application will now close.",
                "normal"
            )
            # Give the notification time to show, then quit
            GLib.timeout_add(1500, Gtk.main_quit)
        else:
            self.send_notification(
                "Uninstall Issue",
                "Some files may not have been removed. You may need to run the uninstall manually with sudo.",
                "normal"
            )

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
