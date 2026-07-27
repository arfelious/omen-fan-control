#!/usr/bin/env bash
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

if ! command -v docker &>/dev/null; then
    echo "Error: docker not found." >&2
    exit 1
fi

IMAGE="${DEB_BUILD_IMAGE:-debian:bookworm}"
echo "Pulling $IMAGE ..."
docker pull "$IMAGE"

echo "Building .deb in container ..."
docker run --rm --network=host \
    -v "$REPO_ROOT:/src:rw" \
    -w /src \
    "$IMAGE" \
    bash -ex -c '
        apt-get update
        apt-get install -y \
            debhelper dpkg-dev \
            dkms \
            python3 python3-pip python3-venv python3-build python3-installer python3-hatchling
        ./deb/build.sh "'"$TARGET"'"
    '

echo "Built packages in deb/build/:"
ls -la "$REPO_ROOT/deb/build/"*.deb 2>/dev/null || true