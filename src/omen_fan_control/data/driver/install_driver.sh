#!/bin/bash
set -e

# HP Omen Fan Control - Permanent Driver Installation
# Uses same layout as DKMS package: /usr/src/hp-wmi-omen-1.0/{dkms.conf, src/Makefile, src/hp-wmi-omen/}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DKMS_NAME="hp-wmi-omen"
DKMS_VERSION="1.0"
DKMS_SRC="/usr/src/${DKMS_NAME}-${DKMS_VERSION}"
BUILD_DIR="${DKMS_SRC}/src/hp-wmi-omen"

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
    if dkms status | grep -q "${DKMS_NAME}"; then
        echo "Removing old DKMS module..."
        sudo dkms remove "${DKMS_NAME}/${DKMS_VERSION}" --all 2>/dev/null || true
    fi
    sudo rm -rf "$DKMS_SRC"
    sudo mkdir -p "${DKMS_SRC}/src"
    sudo cp "$SCRIPT_DIR/dkms.conf" "$DKMS_SRC/"
    # Same as PKGBUILD: replace placeholders so DKMS finds the module
    sudo sed -e "s/@PKGNAME@/${DKMS_NAME}/g" -e "s/@PKGVER@/${DKMS_VERSION}/g" -i "$DKMS_SRC/dkms.conf"
    sudo cp "$SCRIPT_DIR/src/Makefile" "$DKMS_SRC/src/"
    sudo cp -dr --no-preserve=ownership "$SCRIPT_DIR/hp-wmi-omen" "$DKMS_SRC/src/"
    backup_drivers
    sudo dkms add -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    sudo dkms build -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    sudo dkms install -m "${DKMS_NAME}" -v "${DKMS_VERSION}"
    echo "DKMS installation complete!"
}

install_with_hooks() {
    local distro="$1"
    echo "Installing with kernel hooks (distro: $distro)..."
    sudo rm -rf "$DKMS_SRC"
    sudo mkdir -p "${DKMS_SRC}/src"
    sudo cp "$SCRIPT_DIR/dkms.conf" "$DKMS_SRC/"
    sudo sed -e "s/@PKGNAME@/${DKMS_NAME}/g" -e "s/@PKGVER@/${DKMS_VERSION}/g" -i "$DKMS_SRC/dkms.conf"
    sudo cp "$SCRIPT_DIR/src/Makefile" "$DKMS_SRC/src/"
    sudo cp -dr --no-preserve=ownership "$SCRIPT_DIR/hp-wmi-omen" "$DKMS_SRC/src/"
    cd "$BUILD_DIR"
    make -C "/lib/modules/$(uname -r)/build" M="$(pwd)" modules
    backup_drivers
    DEST_DIR="/lib/modules/$(uname -r)/kernel/drivers/platform/x86/hp"
    sudo mkdir -p "$DEST_DIR"
    sudo install -m 644 hp-wmi.ko "$DEST_DIR/hp-wmi.ko"
    case "$distro" in
        arch|manjaro|endeavouros|garuda)
            echo "Installing Arch Linux pacman hook..."
            sudo mkdir -p /etc/pacman.d/hooks
            sudo cp "$SCRIPT_DIR/hooks/90-hp-wmi-omen.hook" /etc/pacman.d/hooks/
            ;;
        debian|ubuntu|linuxmint|pop)
            sudo install -m 755 "$SCRIPT_DIR/hooks/zz-hp-wmi-omen" /etc/kernel/postinst.d/
            ;;
        fedora|rhel|centos|rocky|almalinux)
            sudo mkdir -p /etc/kernel/install.d
            sudo install -m 755 "$SCRIPT_DIR/hooks/99-hp-wmi-omen.install" /etc/kernel/install.d/
            ;;
        *)
            echo "Warning: Unknown distro. Module installed for current kernel only."
            ;;
    esac
    make clean || true
    echo "Hook-based installation complete!"
}

backup_drivers() {
    echo "Backing up existing drivers..."
    find "/lib/modules/$(uname -r)/kernel/drivers/platform/x86/hp" "/lib/modules/$(uname -r)/updates" -name "hp-wmi.ko*" 2>/dev/null | while read -r OLD_DRIVER; do
        # Avoid double-backing up (skip .bak files entirely)
        [[ "$OLD_DRIVER" == *".bak" ]] && continue
        # If a .bak already exists for this driver, do not overwrite
        if [ ! -f "${OLD_DRIVER}.bak" ]; then
            echo "Backing up: $OLD_DRIVER"
            sudo cp "$OLD_DRIVER" "${OLD_DRIVER}.bak"
        else
            echo "Clean backup already exists for: $OLD_DRIVER (Skipping Backup)"
        fi
        echo "Removing conflicting module: $OLD_DRIVER"
        sudo rm -f "$OLD_DRIVER"
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
    if command -v update-initramfs >/dev/null; then
        sudo update-initramfs -u
    elif command -v mkinitcpio >/dev/null; then
        sudo mkinitcpio -P
    elif command -v dracut >/dev/null; then
        sudo dracut --force
    fi
}

main() {
    echo "=== HP Omen Fan Control - Permanent Installation ==="
    DISTRO=$(detect_distro)
    echo "Detected distro: $DISTRO"
    FORCE_HOOKS=0
    for arg in "$@"; do
        [[ "$arg" == "--no-dkms" ]] && FORCE_HOOKS=1
    done
    if [ "$FORCE_HOOKS" -eq 1 ]; then
        install_with_hooks "$DISTRO"
    elif command -v dkms >/dev/null 2>&1; then
        install_with_dkms
    else
        install_with_hooks "$DISTRO"
    fi
    reload_driver
    update_initramfs
    echo ""
    echo "=== Installation Complete ==="
}

main "$@"