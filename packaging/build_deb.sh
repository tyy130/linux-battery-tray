#!/bin/bash
set -e

# Clean up
rm -rf build
mkdir -p build/DEBIAN
mkdir -p build/opt/battery-indicator/icons/hicolor/scalable/status
mkdir -p build/usr/share/applications
mkdir -p build/usr/bin

# Set permissions for DEBIAN directory
chmod 755 build/DEBIAN

# Copy control files
cp packaging/DEBIAN/control build/DEBIAN/
cp packaging/DEBIAN/postinst build/DEBIAN/
chmod 755 build/DEBIAN/postinst

# Copy application files
cp battery_indicator.py build/opt/battery-indicator/
cp config.py build/opt/battery-indicator/
chmod 755 build/opt/battery-indicator/battery_indicator.py

# Copy custom icons with theme structure
cp icons/*.svg build/opt/battery-indicator/icons/
cp icons/index.theme build/opt/battery-indicator/icons/
cp icons/hicolor/scalable/status/*.svg build/opt/battery-indicator/icons/hicolor/scalable/status/

# Copy desktop file
cp battery-indicator.desktop build/usr/share/applications/

# Create symlink
ln -s /opt/battery-indicator/battery_indicator.py build/usr/bin/battery-indicator

# Build package
dpkg-deb --build build linux-battery-tray_1.1.0_all.deb

echo "Package built: linux-battery-tray_1.1.0_all.deb"
