#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVER_SRC="$REPO_ROOT/src/omen_fan_control/data/driver"
BUILD_DIR="$REPO_ROOT/deb/build"

build_hp_wmi_omen_dkms() {
    echo "=== Building hp-wmi-omen-dkms ==="
    rm -rf "$BUILD_DIR/hp-wmi-omen-dkms"
    mkdir -p "$BUILD_DIR/hp-wmi-omen-dkms"
    cp "$DRIVER_SRC/dkms.conf" "$BUILD_DIR/hp-wmi-omen-dkms/"
    mkdir -p "$BUILD_DIR/hp-wmi-omen-dkms/src"
    cp "$DRIVER_SRC/src/Makefile" "$BUILD_DIR/hp-wmi-omen-dkms/src/"
    cp -r "$DRIVER_SRC/hp-wmi-omen" "$BUILD_DIR/hp-wmi-omen-dkms/src/"
    cp -r "$REPO_ROOT/deb/hp-wmi-omen-dkms/debian" "$BUILD_DIR/hp-wmi-omen-dkms/"
    (cd "$BUILD_DIR/hp-wmi-omen-dkms" && dpkg-buildpackage -b -uc -us)
    echo "Built: $BUILD_DIR/hp-wmi-omen-dkms_1.0_*.deb"
}

build_omen_fan_control_dkms() {
    echo "=== Building omen-fan-control-dkms (metapackage with DKMS auto-setup) ==="
    rm -rf "$BUILD_DIR/omen-fan-control-dkms"
    mkdir -p "$BUILD_DIR/omen-fan-control-dkms"
    cp -r "$REPO_ROOT/deb/omen-fan-control-dkms/debian" "$BUILD_DIR/omen-fan-control-dkms/"
    (cd "$BUILD_DIR/omen-fan-control-dkms" && dpkg-buildpackage -b -uc -us)
    echo "Built: $BUILD_DIR/omen-fan-control-dkms_1.0.0_*.deb"
}

build_omen_fan_control() {
    echo "=== Building omen-fan-control ==="
    rm -rf "$BUILD_DIR/omen-fan-control"
    mkdir -p "$BUILD_DIR/omen-fan-control"
    cp "$REPO_ROOT/pyproject.toml" "$BUILD_DIR/omen-fan-control/"
    cp -r "$REPO_ROOT/src" "$BUILD_DIR/omen-fan-control/"
    for f in README.md LICENSE.md; do
        [[ -f "$REPO_ROOT/$f" ]] && cp "$REPO_ROOT/$f" "$BUILD_DIR/omen-fan-control/"
    done
    cp -r "$REPO_ROOT/deb/omen-fan-control/debian" "$BUILD_DIR/omen-fan-control/"
    (cd "$BUILD_DIR/omen-fan-control" && dpkg-buildpackage -b -uc -us)
    echo "Built: $BUILD_DIR/omen-fan-control_1.0.0_*.deb"
}

main() {
    local target="${1:-all}"
    case "$target" in
        hp-wmi-omen-dkms) build_hp_wmi_omen_dkms ;;
        omen-fan-control) build_omen_fan_control ;;
        omen-fan-control-dkms) build_omen_fan_control_dkms ;;
        all)
            build_hp_wmi_omen_dkms
            build_omen_fan_control
            build_omen_fan_control_dkms
            ;;
        *)
            echo "Usage: $0 [hp-wmi-omen-dkms|omen-fan-control|omen-fan-control-dkms|all]" >&2
            exit 1
            ;;
    esac
}

main "$@"
