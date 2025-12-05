#!/bin/bash
set -e

# Clean up
rm -rf build
mkdir -p build/DEBIAN
mkdir -p build/opt/battery-indicator
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

# Copy desktop file
cp battery-indicator.desktop build/usr/share/applications/

# Create symlink
ln -s /opt/battery-indicator/battery_indicator.py build/usr/bin/battery-indicator

# Build package
dpkg-deb --build build linux-battery-tray_1.0.0_all.deb

echo "Package built: linux-battery-tray_1.0.0_all.deb"
