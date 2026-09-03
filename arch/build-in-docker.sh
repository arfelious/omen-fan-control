#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PKG_TARGET="${1:-all}"

if ! command -v docker &>/dev/null; then
    echo "Error: docker not found." >&2
    exit 1
fi

IMAGE="${ARCH_BUILD_IMAGE:-omen-fan-control-arch-builder}"

echo "=== Building builder image ($IMAGE) ==="
docker build -t "$IMAGE" "$REPO_ROOT/arch"

build_pkg() {
    local pkgdir="$1"
    local pkgname
    pkgname=$(basename "$pkgdir")

    echo "=== Building $pkgname ==="
    docker run --rm \
        -v "$REPO_ROOT:/src:rw" \
        -w "/src/arch/$pkgname" \
        -u builder \
        "$IMAGE" \
        bash -ec '
            set -e
            # Install previously-built packages so inter-package deps resolve
            for f in /src/arch/*/*.pkg.tar.zst; do
                [ -f "$f" ] && sudo pacman -U --noconfirm "$f" 2>/dev/null || true
            done
            makepkg -f --noconfirm --syncdeps 2>&1
        '

    echo "=== $pkgname built ==="
}

case "$PKG_TARGET" in
    all|omen-fan-control)
        build_pkg "$REPO_ROOT/arch/omen-fan-control"
        ;;
    *)
        echo "Usage: $0 [omen-fan-control|all]" >&2
        exit 1
        ;;
esac

echo ""
echo "=== Built packages ==="
find "$REPO_ROOT/arch" -maxdepth 3 -name '*.pkg.tar.zst' -exec ls -lh {} \;
echo ""
echo "Packages are in the arch/ subdirectories alongside their PKGBUILDs."
