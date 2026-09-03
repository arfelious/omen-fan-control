from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, TypedDict, cast

from ._constants import (
    CONFIG_FILE,
    CONFIG_VERSION,
    DEFAULT_CALIBRATION_WAIT,
    DEFAULT_WATCHDOG_INTERVAL,
    VOLATILE_CONFIG_FILE,
)


class ConfigDict(TypedDict, total=False):
    version: int
    fan_max: int
    fan1_max: int
    fan2_max: int
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
    reference_sensor: str
    log_level: str
    cleaner_enabled: bool
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
    manual_cpu_max_rpm: int
    manual_gpu_max_rpm: int
    bypass_calibration: bool
    windows_config_imported: bool
    windows_max_rpm: int
    windows_cpu_max_rpm: int
    windows_gpu_max_rpm: int
    auto_cleaner_enabled: bool
    cleaner_interval_minutes: int
    custom_cleaner_interval: bool
    cleaner_duration_sec: int
    use_advanced_fan_control: bool
    max_fan_speed_strategy: str
    fan_control_method: str
    asymmetrical_offset_rpm: int
    gpu_curve: list[list[float]]
    gpu_manual_pwm: int
    gpu_curve_use_gpu_temp: bool
    last_patched_cpu_max_rpm: int | None
    last_patched_gpu_max_rpm: int | None


DEFAULT_CONFIG: ConfigDict = {
    "version": CONFIG_VERSION,
    "fan1_max": 0,
    "fan2_max": 0,
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
    "reference_sensor": "cpu",
    "use_manual_max_rpm": False,
    "manual_cpu_max_rpm": 6000,
    "manual_gpu_max_rpm": 5800,
    "use_advanced_fan_control": False,
    "max_fan_speed_strategy": "calibration",
    "fan_control_method": "percentage",
    "asymmetrical_offset_rpm": 200,
    "gpu_curve": [],
    "gpu_manual_pwm": 128,
    "gpu_curve_use_gpu_temp": True,
    "last_patched_cpu_max_rpm": None,
    "last_patched_gpu_max_rpm": None,
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

    # ── Migration: single fan_max -> dual fan1_max / fan2_max ──
    if "fan_max" in config:
        legacy_fan_max = config.get("fan_max", 0)
        if legacy_fan_max > 0:
            if "fan1_max" not in config or config.get("fan1_max", 0) == 0:
                config["fan1_max"] = legacy_fan_max
            if "fan2_max" not in config or config.get("fan2_max", 0) == 0:
                config["fan2_max"] = legacy_fan_max

    # ── Migration: single manual_max_rpm -> dual manual_cpu_max_rpm / manual_gpu_max_rpm ──
    if "manual_max_rpm" in config:
        legacy_val = config.get("manual_max_rpm", 5800)
        if "manual_cpu_max_rpm" not in config:
            config["manual_cpu_max_rpm"] = config.get("fan1_max") or legacy_val
        if "manual_gpu_max_rpm" not in config:
            config["manual_gpu_max_rpm"] = config.get("fan2_max") or legacy_val

    if "windows_max_rpm" in config:
        legacy_win = config.get("windows_max_rpm")
        if "windows_cpu_max_rpm" not in config:
            config["windows_cpu_max_rpm"] = legacy_win
        if "windows_gpu_max_rpm" not in config:
            config["windows_gpu_max_rpm"] = legacy_win

    # ── Migration: use_manual_max_rpm -> use_advanced_fan_control ──
    if config.get("use_manual_max_rpm") and "use_advanced_fan_control" not in config:
        config["use_advanced_fan_control"] = True
        config["max_fan_speed_strategy"] = "custom"

    # ── Cleanup obsolete shutdown_hook_enabled and residual service file ──
    config.pop("shutdown_hook_enabled", None)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        shutdown_svc = Path("/etc/systemd/system/omen-fan-shutdown.service")
        if shutdown_svc.exists():
            try:
                import subprocess
                subprocess.run(["systemctl", "stop", "omen-fan-shutdown.service"], check=False, capture_output=True)
                subprocess.run(["systemctl", "disable", "omen-fan-shutdown.service"], check=False, capture_output=True)
                shutdown_svc.unlink(missing_ok=True)
                subprocess.run(["systemctl", "daemon-reload"], check=False, capture_output=True)
            except Exception:
                pass

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

    config.pop("fan_max", None)
    config.pop("manual_max_rpm", None)

    with open(target_path, "w") as f:
        json.dump(config, f, indent=4)
        f.flush()
        try:
            import os
            os.fsync(f.fileno())
        except Exception:
            pass
