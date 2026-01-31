#!/bin/bash
set -e

# HP Omen Fan Control - Permanent Driver Installation
# Hybrid approach: Uses DKMS if available, otherwise installs kernel hooks

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DKMS_NAME="hp-wmi-omen"
DKMS_VERSION="1.0"
DKMS_SRC="/usr/src/${DKMS_NAME}-${DKMS_VERSION}"
HOOK_SRC_DIR="/usr/src/${DKMS_NAME}"

detect_distro() {
    if [ -f /etc/os-release ]; then
        . /etc/os-release
        echo "$ID"
    elif [ -f /etc/arch-release ]; then
        echo "arch"
    elif [ -f /etc/debian_version ]; then
        echo "debian"
    elif [ -f /etc/fedora-release ]; then
        echo "fedora"
    else
        echo "unknown"
    fi
}

install_with_dkms() {
    echo "Installing with DKMS..."
    
    # Remove old DKMS module if exists
    if dkms status | grep -q "${DKMS_NAME}"; then
        echo "Removing old DKMS module..."
        sudo dkms remove "${DKMS_NAME}/${DKMS_VERSION}" --all 2>/dev/null || true
    fi
    
    # Create DKMS source directory
    sudo rm -rf "$DKMS_SRC"
    sudo mkdir -p "$DKMS_SRC"
    
    # Copy source files
    sudo cp "$SCRIPT_DIR/hp-wmi.c" "$DKMS_SRC/"
    sudo cp "$SCRIPT_DIR/Makefile" "$DKMS_SRC/"
    sudo cp "$SCRIPT_DIR/dkms.conf" "$DKMS_SRC/"
    
    # Backup existing drivers
    backup_drivers
    
    # Add, build, and install via DKMS
    sudo dkms add -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    sudo dkms build -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    sudo dkms install -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    
    echo "DKMS installation complete!"
}

install_with_hooks() {
    local distro="$1"
    echo "Installing with kernel hooks (distro: $distro)..."
    
    # Build module for current kernel first
    make -C "$SCRIPT_DIR"
    
    # Backup and install for current kernel
    backup_drivers
    
    DEST_DIR="/lib/modules/$(uname -r)/kernel/drivers/platform/x86/hp"
    sudo mkdir -p "$DEST_DIR"
    sudo install -m 644 "$SCRIPT_DIR/hp-wmi.ko" "$DEST_DIR/hp-wmi.ko"
    
    # Copy source for future builds
    sudo rm -rf "$HOOK_SRC_DIR"
    sudo mkdir -p "$HOOK_SRC_DIR"
    sudo cp "$SCRIPT_DIR/hp-wmi.c" "$HOOK_SRC_DIR/"
    sudo cp "$SCRIPT_DIR/Makefile" "$HOOK_SRC_DIR/"
    
    # Install appropriate hook based on distro
    case "$distro" in
        arch|manjaro|endeavouros|garuda)
            echo "Installing Arch Linux pacman hook..."
            sudo mkdir -p /etc/pacman.d/hooks
            sudo cp "$SCRIPT_DIR/hooks/90-hp-wmi-omen.hook" /etc/pacman.d/hooks/
            ;;
        debian|ubuntu|linuxmint|pop)
            echo "Installing Debian/Ubuntu kernel hook..."
            sudo install -m 755 "$SCRIPT_DIR/hooks/zz-hp-wmi-omen" /etc/kernel/postinst.d/
            ;;
        fedora|rhel|centos|rocky|almalinux)
            echo "Installing Fedora/RHEL kernel hook..."
            sudo mkdir -p /etc/kernel/install.d
            sudo install -m 755 "$SCRIPT_DIR/hooks/99-hp-wmi-omen.install" /etc/kernel/install.d/
            ;;
        *)
            echo "Warning: Unknown distro '$distro'. No kernel hook installed."
            echo "The module is installed for the current kernel only."
            echo "You may need to manually reinstall after kernel updates."
            ;;
    esac
    
    make -C "$SCRIPT_DIR" clean
    echo "Hook-based installation complete!"
}

backup_drivers() {
    echo "Backing up existing drivers..."
    # Check both standard path and updates (DKMS) path
    find "/lib/modules/$(uname -r)/kernel/drivers/platform/x86/hp" "/lib/modules/$(uname -r)/updates" -name "hp-wmi.ko*" 2>/dev/null | while read -r OLD_DRIVER; do
        if [[ "$OLD_DRIVER" == *"$SCRIPT_DIR"* ]]; then continue; fi
        
        # Avoid double-backing up (skip .bak files)
        if [[ "$OLD_DRIVER" != *".bak" ]]; then
            # If a backup doesn't exist, create one
            if [ ! -f "$OLD_DRIVER.bak" ]; then
                echo "Backing up: $OLD_DRIVER"
                sudo cp "$OLD_DRIVER" "$OLD_DRIVER.bak"
            fi
            
            # Important: Remove the conflicting module so depmod picks the new one
            echo "Removing conflicting module: $OLD_DRIVER"
            sudo rm -f "$OLD_DRIVER"
        fi
    done
}

reload_driver() {
    echo "Reloading driver..."
    sudo depmod -a
    
    if sudo modprobe -r hp-wmi 2>/dev/null; then
        sudo modprobe hp-wmi
        echo "Driver reloaded successfully!"
    else
        echo "Warning: Could not unload driver. A reboot may be required."
    fi
}

update_initramfs() {
    echo "Updating initramfs..."
    if command -v update-initramfs >/dev/null; then
        sudo update-initramfs -u
    elif command -v mkinitcpio >/dev/null; then
        sudo mkinitcpio -P
    elif command -v dracut >/dev/null; then
        sudo dracut --force
    fi
}

# Main installation logic
main() {
    echo "=== HP Omen Fan Control - Permanent Installation ==="
    
    DISTRO=$(detect_distro)
    echo "Detected distro: $DISTRO"
    
    FORCE_HOOKS=0
    for arg in "$@"; do
        if [ "$arg" == "--no-dkms" ]; then
            FORCE_HOOKS=1
        fi
    done

    if [ "$FORCE_HOOKS" -eq 1 ]; then
        echo "Forcing kernel hooks installation (--no-dkms passed)."
        install_with_hooks "$DISTRO"
    elif command -v dkms >/dev/null 2>&1; then
        echo "DKMS is available."
        install_with_dkms
    else
        echo "DKMS not found. Using kernel hooks fallback."
        install_with_hooks "$DISTRO"
    fi
    
    reload_driver
    update_initramfs
    
    echo ""
    echo "=== Installation Complete ==="
    echo "The patched hp-wmi driver is now installed and will persist across reboots."
}

main "$@"