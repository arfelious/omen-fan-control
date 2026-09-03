from __future__ import annotations

import glob
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Generator

from ._cleaner import FanCleanerMixin
from ._config import ConfigDict, load_config as _load_config, save_config as _save_config
from ._constants import (
    CONFIG_FILE,
    DEFAULT_CALIBRATION_WAIT,
    HWMON_PATH_PATTERN,
    SUPPORTED_BOARDS,
    POSSIBLY_SUPPPORTED_OMEN_BOARDS,
)
from ._driver import DriverInstallerMixin
from ._service import ServiceManagerMixin


class FanController(
    FanCleanerMixin,
    DriverInstallerMixin,
    ServiceManagerMixin,
):
    def __init__(self, config_path: str | Path | None = None) -> None:
        self._find_paths()
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = CONFIG_FILE

        self.config = self.load_config()

        if self.config.get("cleaner_in_progress", False):
            start_ts = self.config.get("cleaner_start_time", 0)
            if not start_ts or (time.time() - start_ts >= 30):
                self.emergency_stop_fan_cleaning()

    def check_board_support(self) -> tuple[str, str]:
        cached = self.config.get("cached_board_name")
        if cached:
            board_name = str(cached)
        else:
            try:
                with open("/sys/class/dmi/id/board_name") as f:
                    board_name = f.read().strip()
                self.config["cached_board_name"] = board_name
                self.save_config()
            except Exception as e:
                print(f"Error reading board name: {e}")
                return "UNSUPPORTED", "Unknown"

        if board_name in SUPPORTED_BOARDS:
            return "SUPPORTED", board_name
        elif board_name in POSSIBLY_SUPPPORTED_OMEN_BOARDS:
            return "POSSIBLY_SUPPORTED", board_name
        return "UNSUPPORTED", board_name

    def _find_paths(self) -> None:
        self.cpu_temp_path = self._find_cpu_temp_path()
        paths = glob.glob(HWMON_PATH_PATTERN)
        if not paths:
            self.hwmon_path = None
            self.pwm1_enable_path = None
            self.pwm1_path = None
            self.pwm2_path = None
            self.fan1_input_path = None
            self.fan2_input_path = None
            return

        self.hwmon_path = Path(paths[0])
        self.pwm1_enable_path = self.hwmon_path / "pwm1_enable"
        self.pwm1_path = self.hwmon_path / "pwm1"
        self.pwm2_path = self.hwmon_path / "pwm2"
        self.fan1_input_path = self.hwmon_path / "fan1_input"
        self.fan2_input_path = self.hwmon_path / "fan2_input"
        self.cpu_temp_path = self._find_cpu_temp_path()

    def _find_cpu_temp_path(self) -> Path | None:
        for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                name_path = hwmon / "name"
                if not name_path.exists():
                    continue
                with open(name_path) as f:
                    name = f.read().strip()
                if name in ["coretemp", "k10temp"]:
                    temp_path = hwmon / "temp1_input"
                    if temp_path.exists():
                        return temp_path
            except Exception:
                continue

        if Path("/sys/class/thermal/thermal_zone0/temp").exists():
            return Path("/sys/class/thermal/thermal_zone0/temp")
        return None

    def load_config(self) -> ConfigDict:
        return _load_config(self.config_path)

    def save_config(self, volatile: bool = False, source: str | None = None) -> None:
        _save_config(self.config, self.config_path, volatile=volatile, source=source)

    def write_sys_file(self, path: Path | str | None, value: int | str) -> None:
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(str(value))
        except PermissionError:
            print(f"Permission denied writing to {path}. Are you running as root?")
        except Exception as e:
            print(f"Error writing to {path}: {e}")

    def read_sys_file(self, path: Path | None) -> str | None:
        if not path or not path.exists():
            return None
        try:
            with open(path) as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error reading {path}: {e}")
            return None

    def parse_hwmon_rpm(self, val: str | None) -> tuple[int, bool]:
        if not val:
            return 0, False
        try:
            raw_rpm = int(val)
            if raw_rpm >= 12800:
                reverse_bit_speed = raw_rpm // 100
                actual_speed = (reverse_bit_speed & 0x7F) * 100
                return actual_speed, True
            return raw_rpm, False
        except Exception:
            return 0, False

    def get_fan_speed(self) -> int:
        val1 = self.read_sys_file(self.fan1_input_path)
        val2 = self.read_sys_file(self.fan2_input_path)

        rpm1, is_rev1 = self.parse_hwmon_rpm(val1)
        rpm2, is_rev2 = self.parse_hwmon_rpm(val2)

        if val1 or val2:
            raw_log = f"sysfs fan1={val1}, fan2={val2}"
            if not hasattr(self, "_last_logged_raw_rpm") or self._last_logged_raw_rpm != raw_log:
                self._last_logged_raw_rpm = raw_log
                self.log_cleaner(f"HWMON SYSFS READINGS -> {raw_log} => Parsed RPM: {max(rpm1, rpm2)} (Reverse: {is_rev1 or is_rev2})")

        return max(rpm1, rpm2)

    def get_fan_speed_info(self) -> tuple[int, bool]:
        val1 = self.read_sys_file(self.fan1_input_path)
        val2 = self.read_sys_file(self.fan2_input_path)

        rpm1, is_rev1 = self.parse_hwmon_rpm(val1)
        rpm2, is_rev2 = self.parse_hwmon_rpm(val2)

        is_reverse = is_rev1 or is_rev2 or self.config.get("cleaner_in_progress", False)
        return max(rpm1, rpm2), is_reverse

    def get_both_fan_speeds(self) -> list[tuple[str, int, bool]]:
        val1 = self.read_sys_file(self.fan1_input_path)
        val2 = self.read_sys_file(self.fan2_input_path)

        rpm1, is_rev1 = self.parse_hwmon_rpm(val1)
        rpm2, is_rev2 = self.parse_hwmon_rpm(val2)

        is_cleaner = self.config.get("cleaner_in_progress", False)
        return [
            ("Fan 1 (CPU)", rpm1, is_rev1 or is_cleaner),
            ("Fan 2 (GPU)", rpm2, is_rev2 or is_cleaner),
        ]

    def get_cpu_temp(self) -> int:
        if self.cpu_temp_path:
            val = self.read_sys_file(self.cpu_temp_path)
            return int(val) // 1000 if val else 0
        return 0

    def has_gpu(self) -> bool:
        if hasattr(self, "_has_gpu_cache"):
            return self._has_gpu_cache
        self._has_gpu_cache = self.get_gpu_temp() > 0
        return self._has_gpu_cache

    def get_gpu_temp(self) -> int:
        try:
            res = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
                                 capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return int(res.stdout.strip())
        except Exception:
            pass

        try:
            for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
                name_path = hwmon / "name"
                if name_path.exists():
                    with open(name_path) as f:
                        name = f.read().strip()
                    if "amdgpu" in name.lower():
                        temp_path = hwmon / "temp1_input"
                        if temp_path.exists():
                            val = self.read_sys_file(temp_path)
                            return int(val) // 1000 if val else 0
        except Exception:
            pass

        return 0

    def get_reference_temp(self) -> int:
        sensor = self.config.get("reference_sensor", "cpu")
        if sensor == "gpu":
            gpu_temp = self.get_gpu_temp()
            if gpu_temp > 0:
                return gpu_temp
        return self.get_cpu_temp()

    def get_all_core_temps(self) -> list[tuple[str, int]]:
        core_temps: list[tuple[int, str, int]] = []
        package_temps: list[tuple[str, int]] = []

        if not self.cpu_temp_path:
            return []

        hwmon_dir = self.cpu_temp_path.parent

        for f in hwmon_dir.glob("temp*_input"):
            try:
                label_file = f.with_name(f.name.replace("input", "label"))
                if label_file.exists():
                    label = self.read_sys_file(label_file)
                else:
                    label = f.name

                if not label:
                    continue

                val = self.read_sys_file(f)
                if not val:
                    continue
                temp = int(val) // 1000

                if "Core" in label:
                    try:
                        idx = int(label.split()[-1])
                        core_temps.append((idx, label, temp))
                    except Exception:
                        core_temps.append((999, label, temp))
                elif "Package" in label:
                    package_temps.append((label, temp))
            except Exception:
                continue

        core_temps.sort(key=lambda x: x[0])

        params: list[tuple[str, int]] = []
        for p in package_temps:
            params.append(p)
        for c in core_temps:
            params.append((c[1], c[2]))

        return params

    def set_fan_mode(self, mode: str) -> None:
        if mode == 'max':
            self.write_sys_file(self.pwm1_enable_path, 0)
        elif mode == 'auto':
            self.write_sys_file(self.pwm1_enable_path, 2)

    def get_effective_fan_limits(self) -> tuple[int, int]:
        cal_c = int(self.config.get("fan1_max", 0)) or int(self.config.get("fan_max", 0))
        cal_g = int(self.config.get("fan2_max", 0)) or int(self.config.get("fan_max", 0))

        if self.config.get("use_advanced_fan_control", False):
            strat = self.config.get("max_fan_speed_strategy", "calibration")
            if strat == "omen_defaults":
                cpu_m = int(self.config.get("windows_cpu_max_rpm") or 0)
                gpu_m = int(self.config.get("windows_gpu_max_rpm") or 0)
                if cpu_m > 0 and gpu_m > 0:
                    return cpu_m, gpu_m
                if cal_c > 0 or cal_g > 0:
                    return cal_c or cal_g, cal_g or cal_c
                return cpu_m or 6000, gpu_m or 5800
            elif strat == "custom":
                cpu_m = int(self.config.get("manual_cpu_max_rpm") or 0)
                gpu_m = int(self.config.get("manual_gpu_max_rpm") or 0)
                if cpu_m > 0 and gpu_m > 0:
                    return cpu_m, gpu_m
                if cal_c > 0 or cal_g > 0:
                    return cal_c or cal_g, cal_g or cal_c
                return cpu_m or 6000, gpu_m or 5800
            else: # calibration
                if cal_c > 0 or cal_g > 0:
                    return cal_c or cal_g, cal_g or cal_c
                return 6000, 5800
        
        # Standard flow / default behavior: use calibrated value if calibrated max exists
        if cal_c > 0 or cal_g > 0:
            return cal_c or cal_g, cal_g or cal_c
        return 6000, 5800

    def get_effective_fan_max(self) -> int:
        cpu_m, gpu_m = self.get_effective_fan_limits()
        return max(cpu_m, gpu_m)

    def set_fan_pwm(self, value: int, gpu_value: int | None = None) -> None:
        current_enable = self.read_sys_file(self.pwm1_enable_path)
        if current_enable != "1":
            self.write_sys_file(self.pwm1_enable_path, 1)
        val_str = str(int(value))
        self.write_sys_file(self.pwm1_path, val_str)
        if self.pwm2_path and self.pwm2_path.exists():
            gpu_val_str = str(int(gpu_value)) if gpu_value is not None else val_str
            self.write_sys_file(self.pwm2_path, gpu_val_str)

    def calculate_target_pwm(self, current_temp: int, curve: list[list[float]] | None = None) -> int | None:
        if curve is None:
            curve = self.config.get("curve", [])
        if not curve:
            return None

        sorted_curve = sorted(curve, key=lambda p: p[0])

        target_speed_percent = 0

        if current_temp <= sorted_curve[0][0]:
            target_speed_percent = sorted_curve[0][1]
        elif current_temp >= sorted_curve[-1][0]:
            target_speed_percent = sorted_curve[-1][1]
        else:
            for i in range(len(sorted_curve) - 1):
                p1 = sorted_curve[i]
                p2 = sorted_curve[i + 1]
                if p1[0] <= current_temp <= p2[0]:
                    interp_mode = self.config.get("curve_interpolation", "smooth")
                    if interp_mode == "discrete":
                        target_speed_percent = p1[1]
                    else:
                        denom = p2[0] - p1[0]
                        if denom == 0:
                            target_speed_percent = p2[1]
                        else:
                            ratio = (current_temp - p1[0]) / denom
                            target_speed_percent = p1[1] + ratio * (p2[1] - p1[1])
                    break

        return int(round(target_speed_percent / 100 * 255))

    def calculate_dual_target_pwm(self, cpu_temp: int, gpu_temp: int | None = None) -> tuple[int, int]:
        method = self.config.get("fan_control_method", "percentage") if self.config.get("use_advanced_fan_control", False) else "percentage"
        cpu_pwm = self.calculate_target_pwm(cpu_temp)
        if cpu_pwm is None:
            cpu_pwm = 0

        if method == "percentage":
            return cpu_pwm, cpu_pwm

        elif method == "asymmetrical":
            cpu_max, gpu_max = self.get_effective_fan_limits()
            if cpu_max <= 0:
                cpu_max = 6000
            if gpu_max <= 0:
                gpu_max = 5800

            cpu_rpm = (cpu_pwm / 255) * cpu_max
            offset = int(self.config.get("asymmetrical_offset_rpm", 200))
            target_gpu_rpm = max(0, min(gpu_max, cpu_rpm + offset))
            gpu_pwm = int(round((target_gpu_rpm / gpu_max) * 255))
            gpu_pwm = max(0, min(255, gpu_pwm))
            return cpu_pwm, gpu_pwm

        elif method == "custom_gpu":
            use_gpu_sensor = self.config.get("gpu_curve_use_gpu_temp", True)
            if use_gpu_sensor and gpu_temp is not None and gpu_temp > 0:
                effective_gpu_temp = gpu_temp
            else:
                ref_sensor = self.config.get("reference_sensor", "cpu")
                if ref_sensor == "gpu" and gpu_temp is not None and gpu_temp > 0:
                    effective_gpu_temp = gpu_temp
                else:
                    effective_gpu_temp = cpu_temp

            gpu_curve = self.config.get("gpu_curve", [])
            if not gpu_curve:
                gpu_pwm = cpu_pwm
            else:
                gpu_pwm = self.calculate_target_pwm(effective_gpu_temp, curve=gpu_curve)
                if gpu_pwm is None:
                    gpu_pwm = cpu_pwm
            return cpu_pwm, gpu_pwm

        return cpu_pwm, cpu_pwm

    def get_dual_manual_pwm(self) -> tuple[int, int]:
        method = self.config.get("fan_control_method", "percentage") if self.config.get("use_advanced_fan_control", False) else "percentage"
        cpu_pwm = max(0, min(255, int(self.config.get("manual_pwm", 128))))

        if method == "percentage":
            return cpu_pwm, cpu_pwm

        elif method == "asymmetrical":
            cpu_max, gpu_max = self.get_effective_fan_limits()
            if cpu_max <= 0:
                cpu_max = 6000
            if gpu_max <= 0:
                gpu_max = 5800
            cpu_rpm = (cpu_pwm / 255) * cpu_max
            offset = int(self.config.get("asymmetrical_offset_rpm", 200))
            target_gpu_rpm = max(0, min(gpu_max, cpu_rpm + offset))
            gpu_pwm = int(round((target_gpu_rpm / gpu_max) * 255))
            return cpu_pwm, max(0, min(255, gpu_pwm))

        elif method == "custom_gpu":
            gpu_pwm = max(0, min(255, int(self.config.get("gpu_manual_pwm", cpu_pwm))))
            return cpu_pwm, gpu_pwm

        return cpu_pwm, cpu_pwm

    def calibrate(self) -> Generator[int, None, tuple[int, int]]:
        print("Starting calibration...")

        try:
            prev_enable = self.read_sys_file(self.pwm1_enable_path) or "2"
            prev_pwm = self.read_sys_file(self.pwm1_path) or "0"
            prev_pwm2 = self.read_sys_file(self.pwm2_path) if (self.pwm2_path and self.pwm2_path.exists()) else None
        except Exception:
            prev_enable = "2"
            prev_pwm = "0"
            prev_pwm2 = None

        self.set_fan_mode('max')

        try:
            wait_time = self.config.get("calibration_wait", DEFAULT_CALIBRATION_WAIT)
            steps = 10
            for i in range(steps):
                time.sleep(wait_time / steps)
                yield int((i + 1) / steps * 100)

            val1 = self.read_sys_file(self.fan1_input_path)
            val2 = self.read_sys_file(self.fan2_input_path)
            rpm1, _ = self.parse_hwmon_rpm(val1)
            rpm2, _ = self.parse_hwmon_rpm(val2)

            self.config["fan1_max"] = rpm1
            self.config["fan2_max"] = rpm2
            self.save_config()

            print(f"Calibration finished: Fan 1={rpm1} RPM, Fan 2={rpm2} RPM")
            return rpm1, rpm2
        except GeneratorExit:
            print("Stopping calibration...")
            raise
        finally:
            try:
                if prev_enable:
                    self.write_sys_file(self.pwm1_enable_path, prev_enable)
                if prev_pwm and str(prev_enable).strip() == "1":
                    self.write_sys_file(self.pwm1_path, prev_pwm)
                    if prev_pwm2 and self.pwm2_path and self.pwm2_path.exists():
                        self.write_sys_file(self.pwm2_path, prev_pwm2)
            except Exception as e:
                print(f"Error restoring fan state: {e}")

    def start_stress_test(self, duration_sec: int, core_count: int | None = None) -> bool:
        if core_count is None:
            core_count = os.cpu_count() or 4

        self.stop_stress_test()

        self.stress_processes = []
        cmd = [sys.executable, "-c", "while True: 9999**9999"]

        print(f"Starting stress test on {core_count} cores...")
        try:
            for _ in range(core_count):
                p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self.stress_processes.append(p)
            return True
        except Exception as e:
            print(f"Error starting stress test: {e}")
            self.stop_stress_test()
            return False

    def stop_stress_test(self) -> None:
        if hasattr(self, 'stress_processes') and self.stress_processes:
            print("Stopping stress test...")
            for p in self.stress_processes:
                try:
                    p.terminate()
                except Exception:
                    pass

            for p in self.stress_processes:
                try:
                    p.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    p.kill()

            self.stress_processes = []
            print("Stopped stress test.")

    def set_bios_control(self, enabled: bool) -> bool:
        try:
            subprocess.run(["modprobe", "ec_sys", "write_support=1"], check=True)
        except Exception as e:
            print(f"Failed to load ec_sys: {e}")
            return False

        ECIO_FILE = "/sys/kernel/debug/ec/ec0/io"
        BIOS_OFFSET = 98
        TIMER_OFFSET = 99
        FAN1_OFFSET = 52
        FAN2_OFFSET = 53

        try:
            with open(ECIO_FILE, "r+b") as ec:
                if not enabled:
                    ec.seek(BIOS_OFFSET)
                    ec.write(bytes([6]))
                    time.sleep(0.1)
                    ec.seek(TIMER_OFFSET)
                    ec.write(bytes([0]))
                else:
                    ec.seek(BIOS_OFFSET)
                    ec.write(bytes([0]))
                    ec.seek(FAN1_OFFSET)
                    ec.write(bytes([0]))
                    ec.seek(FAN2_OFFSET)
                    ec.write(bytes([0]))
            return True
        except Exception as e:
            print(f"Error setting BIOS control: {e}")
            return False
