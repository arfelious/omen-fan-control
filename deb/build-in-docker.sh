#!/usr/bin/env bash
# Build .deb packages inside a Debian container (for testing on non-Debian hosts).
# Requires: Docker (docker run).
# Usage: ./deb/build-in-docker.sh [hp-wmi-omen-dkms|omen-fan-control|all]
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET="${1:-all}"

if ! command -v docker &>/dev/null; then
    echo "Error: docker not found. Install docker to build .deb on this host." >&2
    exit 1
fi

# Use bookworm for a stable, recent Debian
IMAGE="${DEB_BUILD_IMAGE:-debian:bookworm}"

echo "Pulling image $IMAGE (set DEB_BUILD_IMAGE to override) ..."
docker pull "$IMAGE"

echo "Installing build deps and building .deb in container ..."
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

echo "Done. Built packages in deb/build/:"
ls -la "$REPO_ROOT/deb/build/"*.deb 2>/dev/null || true