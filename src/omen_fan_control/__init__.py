# Omen Fan Control - HP Omen/Victus fan control on Linux
# Copyright (C) 2026 arfelious
# SPDX-License-Identifier: GPL-3.0-or-later

from pathlib import Path

__version__ = "1.0.0"


def get_data_dir() -> Path:
    """Root directory for assets, LICENSE, and bundled driver."""
    env = __import__("os").environ.get("OMEN_FAN_CONTROL_DIR")
    if env:
        return Path(env).resolve()
    return Path(__file__).parent.resolve() / "data"


def get_driver_dir() -> Path:
    """Directory containing install_driver.sh, dkms.conf, hooks, hp-wmi-omen/."""
    return get_data_dir() / "driver"


def get_assets_dir() -> Path:
    """Directory containing logo and other GUI assets."""
    return get_data_dir() / "assets"


OMEN_FAN_DIR = get_driver_dir()
