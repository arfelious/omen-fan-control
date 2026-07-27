from __future__ import annotations

import json
from pathlib import Path
from typing import Any, TypedDict, cast

from ._constants import (
    CONFIG_DIR,
    CONFIG_FILE,
    CONFIG_VERSION,
    DEFAULT_CALIBRATION_WAIT,
    DEFAULT_WATCHDOG_INTERVAL,
    VOLATILE_CONFIG_FILE,
)


class ConfigDict(TypedDict, total=False):
    version: int
    fan_max: int
    calibration_wait: int
    watchdog_interval: int
    ma_window: int
    curve: list[list[int]]
    bypass_patch_warning: bool
    mode: str
    manual_pwm: int
    curve_interpolation: str
    bypass_root_warning: bool
    enable_experimental: bool
    thermal_profile: str
    cached_board_name: str | None
    debug_experimental_ui: bool
    shutdown_hook_enabled: bool
    reference_sensor: str
    log_level: str
    cleaner_in_progress: bool
    cleaner_start_time: float | None
    cleaner_transitioning: bool
    cleaner_orig_mode: str
    cleaner_orig_manual: int
    cleaner_mode: str
    cleaner_last_run: float
    cleaner_cycle_id: float
    cleaner_cpu_speed: int
    cleaner_gpu_speed: int
    cleaner_duration: int
    windows_cleaner_duration: int
    install_type: str
    config_source: str
    use_manual_max_rpm: bool
    manual_max_rpm: int
    bypass_calibration: bool
    windows_config_imported: bool
    windows_max_rpm: int
    auto_cleaner_enabled: bool
    cleaner_interval_minutes: int
    custom_cleaner_interval: bool
    cleaner_duration_sec: int


DEFAULT_CONFIG: ConfigDict = {
    "version": CONFIG_VERSION,
    "fan_max": 0,
    "calibration_wait": DEFAULT_CALIBRATION_WAIT,
    "watchdog_interval": DEFAULT_WATCHDOG_INTERVAL,
    "ma_window": 5,
    "curve": [],
    "bypass_patch_warning": False,
    "mode": "auto",
    "manual_pwm": 0,
    "curve_interpolation": "smooth",
    "bypass_root_warning": False,
    "enable_experimental": False,
    "thermal_profile": "omen",
    "cached_board_name": None,
    "debug_experimental_ui": False,
    "shutdown_hook_enabled": False,
    "reference_sensor": "cpu",
}


def load_config(config_path: Path | None = None) -> ConfigDict:
    config: ConfigDict = DEFAULT_CONFIG.copy()

    if config_path is None:
        config_path = CONFIG_FILE

    p_data: dict[str, Any] = {}
    p_time: float = 0
    if config_path.exists():
        try:
            p_time = config_path.stat().st_mtime
            with open(config_path) as f:
                p_data = json.load(f)
        except Exception as e:
            print(f"Error loading persistent config: {e}")

    v_data: dict[str, Any] = {}
    v_time: float = 0
    if VOLATILE_CONFIG_FILE.exists():
        try:
            v_time = VOLATILE_CONFIG_FILE.stat().st_mtime
            with open(VOLATILE_CONFIG_FILE) as f:
                v_data = json.load(f)
        except Exception as e:
            print(f"Error loading volatile config: {e}")

    p_typed: ConfigDict = cast(ConfigDict, p_data)
    v_typed: ConfigDict = cast(ConfigDict, v_data)

    if p_time <= v_time:
        config.update(p_typed)
        config.update(v_typed)
    else:
        config.update(v_typed)
        config.update(p_typed)

    return config


def save_config(
    config: ConfigDict,
    config_path: Path | None = None,
    volatile: bool = False,
    source: str | None = None,
) -> None:
    target_path = VOLATILE_CONFIG_FILE if volatile else (config_path or CONFIG_FILE)

    target_path.parent.mkdir(parents=True, exist_ok=True)

    config["version"] = CONFIG_VERSION
    if source:
        config["config_source"] = source

    with open(target_path, "w") as f:
        json.dump(config, f, indent=4)
        f.flush()
        try:
            import os
            os.fsync(f.fileno())
        except Exception:
            pass
