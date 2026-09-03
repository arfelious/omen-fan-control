#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DRIVER_SRC="$REPO_ROOT/src/omen_fan_control/data/driver"
BUILD_DIR="$REPO_ROOT/deb/build"

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
        omen-fan-control|all)
            build_omen_fan_control
            ;;
        *)
            echo "Usage: $0 [omen-fan-control|all]" >&2
            exit 1
            ;;
    esac
}

main "$@"
