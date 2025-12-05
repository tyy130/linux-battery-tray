#!/bin/bash
#
# Installation script for Linux Battery Tray Indicator
# Supports Ubuntu/Debian, Fedora/RHEL, and Arch Linux
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Installation directory
INSTALL_DIR="/opt/battery-indicator"
DESKTOP_FILE="battery-indicator.desktop"

print_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

print_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Detect the package manager
detect_package_manager() {
    if command -v apt &> /dev/null; then
        echo "apt"
    elif command -v dnf &> /dev/null; then
        echo "dnf"
    elif command -v pacman &> /dev/null; then
        echo "pacman"
    else
        echo "unknown"
    fi
}

# Install dependencies based on package manager
install_dependencies() {
    local pkg_manager=$1

    print_info "Installing dependencies using $pkg_manager..."

    case $pkg_manager in
        apt)
            sudo apt update
            sudo apt install -y \
                python3 \
                python3-gi \
                gir1.2-appindicator3-0.1 \
                gir1.2-gtk-3.0 \
                upower \
                libnotify-bin \
                power-profiles-daemon \
                brightnessctl
            ;;
        dnf)
            sudo dnf install -y \
                python3 \
                python3-gobject \
                libappindicator-gtk3 \
                gtk3 \
                upower \
                libnotify \
                power-profiles-daemon \
                brightnessctl
            ;;
        pacman)
            sudo pacman -Sy --noconfirm \
                python \
                python-gobject \
                libappindicator-gtk3 \
                gtk3 \
                upower \
                libnotify \
                power-profiles-daemon \
                brightnessctl
            ;;
        *)
            print_error "Unknown package manager. Please install dependencies manually:"
            echo "  - python3"
            echo "  - python3-gi (PyGObject)"
            echo "  - AppIndicator3 GObject introspection bindings"
            echo "  - GTK 3.0"
            echo "  - upower"
            echo "  - libnotify (notify-send)"
            echo "  - power-profiles-daemon"
            echo "  - brightnessctl"
            return 1
            ;;
    esac

    print_info "Dependencies installed successfully!"
}

# Install the application files
install_application() {
    print_info "Installing application to $INSTALL_DIR..."

    # Create installation directory
    sudo mkdir -p "$INSTALL_DIR"
    sudo mkdir -p "$INSTALL_DIR/icons/hicolor/scalable/status"

    # Copy application files
    sudo cp battery_indicator.py "$INSTALL_DIR/"
    sudo cp config.py "$INSTALL_DIR/"
    
    # Copy custom icons with proper theme structure
    sudo cp icons/*.svg "$INSTALL_DIR/icons/"
    sudo cp icons/index.theme "$INSTALL_DIR/icons/"
    sudo cp icons/hicolor/scalable/status/*.svg "$INSTALL_DIR/icons/hicolor/scalable/status/"

    # Make main script executable
    sudo chmod +x "$INSTALL_DIR/battery_indicator.py"

    print_info "Application files installed!"
}

# Install desktop entry
install_desktop_entry() {
    local autostart=$1

    print_info "Installing desktop entry..."

    # Install to applications directory
    sudo cp "$DESKTOP_FILE" /usr/share/applications/

    # Optionally install to autostart
    if [ "$autostart" = "yes" ]; then
        mkdir -p "$HOME/.config/autostart"
        cp "$DESKTOP_FILE" "$HOME/.config/autostart/"
        print_info "Autostart entry created!"
    fi

    # Update desktop database
    if command -v update-desktop-database &> /dev/null; then
        sudo update-desktop-database /usr/share/applications/
    fi

    print_info "Desktop entry installed!"
}

# Create a symlink for easy command-line access
create_symlink() {
    print_info "Creating command-line symlink..."
    sudo ln -sf "$INSTALL_DIR/battery_indicator.py" /usr/local/bin/battery-indicator
    print_info "You can now run 'battery-indicator' from the command line!"
}

# Uninstall the application
uninstall() {
    print_info "Uninstalling Battery Indicator..."

    # Remove application directory
    if [ -d "$INSTALL_DIR" ]; then
        sudo rm -rf "$INSTALL_DIR"
        print_info "Removed $INSTALL_DIR"
    fi

    # Remove desktop entry
    if [ -f "/usr/share/applications/$DESKTOP_FILE" ]; then
        sudo rm "/usr/share/applications/$DESKTOP_FILE"
        print_info "Removed desktop entry"
    fi

    # Remove autostart entry
    if [ -f "$HOME/.config/autostart/$DESKTOP_FILE" ]; then
        rm "$HOME/.config/autostart/$DESKTOP_FILE"
        print_info "Removed autostart entry"
    fi

    # Remove symlink
    if [ -L "/usr/local/bin/battery-indicator" ]; then
        sudo rm "/usr/local/bin/battery-indicator"
        print_info "Removed command-line symlink"
    fi

    print_info "Uninstallation complete!"
}

# Display usage information
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  --install           Install the battery indicator (default)"
    echo "  --uninstall         Uninstall the battery indicator"
    echo "  --deps-only         Only install dependencies"
    echo "  --no-autostart      Don't enable autostart on login"
    echo "  --help              Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                  Install with autostart enabled"
    echo "  $0 --no-autostart   Install without autostart"
    echo "  $0 --uninstall      Remove the application"
}

# Main installation function
main() {
    local action="install"
    local autostart="yes"
    local deps_only="no"

    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case $1 in
            --install)
                action="install"
                shift
                ;;
            --uninstall)
                action="uninstall"
                shift
                ;;
            --deps-only)
                deps_only="yes"
                shift
                ;;
            --no-autostart)
                autostart="no"
                shift
                ;;
            --help|-h)
                usage
                exit 0
                ;;
            *)
                print_error "Unknown option: $1"
                usage
                exit 1
                ;;
        esac
    done

    # Execute action
    if [ "$action" = "uninstall" ]; then
        uninstall
        exit 0
    fi

    # Detect package manager
    pkg_manager=$(detect_package_manager)
    print_info "Detected package manager: $pkg_manager"

    # Install dependencies
    install_dependencies "$pkg_manager"

    if [ "$deps_only" = "yes" ]; then
        print_info "Dependencies installed. Skipping application installation."
        exit 0
    fi

    # Check if we're in the right directory
    if [ ! -f "battery_indicator.py" ]; then
        print_error "battery_indicator.py not found. Please run this script from the project directory."
        exit 1
    fi

    # Install application
    install_application
    install_desktop_entry "$autostart"
    create_symlink

    echo ""
    print_info "Installation complete!"
    echo ""
    echo "You can start the battery indicator by:"
    echo "  1. Running 'battery-indicator' from the terminal"
    echo "  2. Finding 'Battery Indicator' in your application menu"
    if [ "$autostart" = "yes" ]; then
        echo "  3. It will start automatically on your next login"
    fi
    echo ""
}

main "$@"
