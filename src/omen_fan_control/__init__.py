# Omen Fan Control - HP Omen/Victus fan control on Linux
# Copyright (C) 2026 arfelious
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

__version__ = "1.0.0"


def get_data_dir() -> Path:
    """Root directory for driver sources, assets, and LICENSE (for installs)."""
    env = __import__("os").environ.get("OMEN_FAN_CONTROL_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).parent.resolve() / "data"


def get_driver_dir() -> Path:
    """Directory containing hp-wmi.c, Makefile, install_driver.sh, dkms.conf, hooks."""
    data = get_data_dir()
    driver = data / "driver"
    return driver if driver.exists() else data


def get_assets_dir() -> Path:
    """Directory containing logo and other GUI assets."""
    return get_data_dir() / "assets"


# Backward compatibility: driver dir is used as OMEN_FAN_DIR in logic (cwd for make/install)
OMEN_FAN_DIR = get_driver_dir()
