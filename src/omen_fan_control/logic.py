# Omen Fan Control - Core logic
# Copyright (C) 2026 arfelious
# SPDX-License-Identifier: GPL-3.0-or-later

import glob
import json
import math
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import OMEN_FAN_DIR

# Subdir containing hp-wmi.c and Makefile (same layout as DKMS package src/hp-wmi-omen)
DRIVER_BUILD_DIR = OMEN_FAN_DIR / "hp-wmi-omen"

# Constants
HWMON_PATH_PATTERN = "/sys/devices/platform/hp-wmi/hwmon/*/"
THERMAL_ZONE_PATH = "/sys/class/thermal/thermal_zone0/temp"
if os.geteuid() == 0:
    CONFIG_DIR = Path("/etc/omen-fan-control")
else:
    CONFIG_DIR = Path(os.path.expanduser("~/.config/omen-fan-control"))

CONFIG_FILE = CONFIG_DIR / "config.json"
DEFAULT_CALIBRATION_WAIT = 30
DEFAULT_WATCHDOG_INTERVAL = 90
CONFIG_VERSION = 1

# Supported Board IDs
SUPPORTED_BOARDS = {
    "84DA", "84DB", "84DC",
    "8572", "8573", "8574", "8575",
    "8600", "8601", "8602", "8603", "8604", "8605", "8606", "8607", "860A",
    "8746", "8747", "8748", "8749", "874A", "8786", "8787", "8788", "878A",
    "878B", "878C", "87B5",
    "886B", "886C", "88C8", "88CB", "88D1", "88D2", "88F4", "88F5", "88F6",
    "88F7", "88FD", "88FE", "88FF",
    "8900", "8901", "8902", "8912", "8917", "8918", "8949", "894A", "89EB",
    "8A15", "8A42", "8BAD",
    "8A25",
    "8BBE", "8BD4", "8BD5", "8C78", "8C99", "8C9C", "8D41"
}

POSSIBLY_SUPPPORTED_OMEN_BOARDS = {
    "84DA", "84DB", "84DC", "8574", "8575", "860A", "87B5", "8572", "8573",
    "8600", "8601", "8602", "8605", "8606", "8607", "8746", "8747", "8749",
    "874A", "8603", "8604", "8748", "886B", "886C", "878A", "878B", "878C",
    "88C8", "88CB", "8786", "8787", "8788", "88D1", "88D2", "88F4", "88FD",
    "88F5", "88F6", "8A13", "8A14", "8A15", "8A16", "88F7", "88FE", "8A17",
    "8A18", "8A19", "8A1A", "8BAD", "8BB0", "88FF", "8900", "8901", "8902",
    "8912", "8917", "8918", "8A97", "8A96", "8D2C", "8949", "8A98", "894A",
    "8B1D", "89EB", "8A4C", "8A4D", "8A4E", "8A40", "8A41", "8A42", "8A43",
    "8A44", "8BA8", "8BA9", "8BAA", "8BAB", "8BAC", "8C76", "8C77", "8C78",
    "8BCA", "8BCB", "8BCD", "8BCF", "8C9B", "8BB3", "8BB4", "8C4D", "8C4E",
    "8C58", "8C75", "8C74", "8C73", "8CC1", "8CC0", "8CF1", "8CF2", "8CF3",
    "8CF4"
}


class FanController:
    def __init__(self, config_path=None):
        self._find_paths()
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = CONFIG_FILE
        self.config = self.load_config()

    def check_board_support(self):
        """Returns (status, board_name). status: SUPPORTED, POSSIBLY_SUPPORTED, UNSUPPORTED."""
        if self.config.get("cached_board_name"):
            board_name = self.config["cached_board_name"]
        else:
            try:
                with open("/sys/class/dmi/id/board_name", "r") as f:
                    board_name = f.read().strip()
                self.config["cached_board_name"] = board_name
                self.save_config()
            except Exception as e:
                print(f"Error reading board name: {e}")
                return "UNSUPPORTED", "Unknown"
        if board_name in SUPPORTED_BOARDS:
            return "SUPPORTED", board_name
        if board_name in POSSIBLY_SUPPPORTED_OMEN_BOARDS:
            return "POSSIBLY_SUPPORTED", board_name
        return "UNSUPPORTED", board_name

    def _find_paths(self):
        self.cpu_temp_path = self._find_cpu_temp_path()
        paths = glob.glob(HWMON_PATH_PATTERN)
        if not paths:
            self.hwmon_path = None
            self.pwm1_enable_path = None
            self.pwm1_path = None
            self.fan1_input_path = None
            return
        self.hwmon_path = Path(paths[0])
        self.pwm1_enable_path = self.hwmon_path / "pwm1_enable"
        self.pwm1_path = self.hwmon_path / "pwm1"
        self.fan1_input_path = self.hwmon_path / "fan1_input"
        self.cpu_temp_path = self._find_cpu_temp_path()

    def _find_cpu_temp_path(self):
        for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
            try:
                name_path = hwmon / "name"
                if not name_path.exists():
                    continue
                with open(name_path, "r") as f:
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

    def load_config(self):
        defaults = {
            "version": CONFIG_VERSION,
            "fan_max": 0,
            "calibration_wait": DEFAULT_CALIBRATION_WAIT,
            "watchdog_interval": DEFAULT_WATCHDOG_INTERVAL,
            "ma_window": 5,
            "curve": [],
            "bypass_warning": False,
            "bypass_patch_warning": False,
            "mode": "auto",
            "manual_pwm": 0,
            "curve_interpolation": "smooth",
            "bypass_root_warning": False,
            "enable_experimental": False,
            "thermal_profile": "omen",
            "cached_board_name": None,
            "debug_experimental_ui": False,
        }
        if not self.config_path.exists():
            return defaults
        try:
            with open(self.config_path, "r") as f:
                data = json.load(f)
            config = defaults.copy()
            config.update(data)
            return config
        except Exception as e:
            print(f"Error loading config: {e}")
            return defaults

    def save_config(self):
        if self.config_path.parent:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
        self.config["version"] = CONFIG_VERSION
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=4)

    def write_sys_file(self, path, value):
        if not path:
            return
        try:
            with open(path, "w") as f:
                f.write(str(value))
        except PermissionError:
            print(f"Permission denied writing to {path}. Are you running as root?")
        except Exception as e:
            print(f"Error writing to {path}: {e}")

    def read_sys_file(self, path):
        if not path or not path.exists():
            return None
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error reading {path}: {e}")
            return None

    def get_fan_speed(self):
        val = self.read_sys_file(self.fan1_input_path)
        return int(val) if val else 0

    def get_cpu_temp(self):
        if self.cpu_temp_path:
            val = self.read_sys_file(self.cpu_temp_path)
            return int(val) // 1000 if val else 0
        return 0

    def get_all_core_temps(self):
        core_temps = []
        package_temps = []
        if not self.cpu_temp_path:
            return []
        hwmon_dir = self.cpu_temp_path.parent
        for f in hwmon_dir.glob("temp*_input"):
            try:
                label_file = f.with_name(f.name.replace("input", "label"))
                label = self.read_sys_file(label_file) if label_file.exists() else f.name
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
        params = list(package_temps)
        for c in core_temps:
            params.append((c[1], c[2]))
        return params

    def set_fan_mode(self, mode):
        if mode == "max":
            self.write_sys_file(self.pwm1_enable_path, 0)
        elif mode == "auto":
            self.write_sys_file(self.pwm1_enable_path, 2)

    def set_fan_pwm(self, value):
        current_enable = self.read_sys_file(self.pwm1_enable_path)
        if current_enable != "1":
            self.write_sys_file(self.pwm1_enable_path, 1)
        self.write_sys_file(self.pwm1_path, str(int(value)))

    def calculate_target_pwm(self, current_temp):
        curve = self.config.get("curve", [])
        if not curve:
            return None
        curve = sorted(curve, key=lambda p: p[0])
        target_speed_percent = 0
        if current_temp <= curve[0][0]:
            target_speed_percent = curve[0][1]
        elif current_temp >= curve[-1][0]:
            target_speed_percent = curve[-1][1]
        else:
            for i in range(len(curve) - 1):
                p1, p2 = curve[i], curve[i + 1]
                if p1[0] <= current_temp <= p2[0]:
                    interp_mode = self.config.get("curve_interpolation", "smooth")
                    if interp_mode == "discrete":
                        target_speed_percent = p1[1]
                    else:
                        denom = p2[0] - p1[0]
                        target_speed_percent = p2[1] if denom == 0 else p1[1] + (current_temp - p1[0]) / denom * (p2[1] - p1[1])
                    break
        return int(round(target_speed_percent / 100 * 255))

    def calibrate(self):
        print("Starting calibration...")
        try:
            prev_enable = self.read_sys_file(self.pwm1_enable_path) or "2"
            prev_pwm = self.read_sys_file(self.pwm1_path) or "0"
        except Exception:
            prev_enable, prev_pwm = "2", "0"
        self.set_fan_mode("max")
        wait_time = self.config.get("calibration_wait", DEFAULT_CALIBRATION_WAIT)
        steps = 10
        for i in range(steps):
            time.sleep(wait_time / steps)
            yield int((i + 1) / steps * 100)
        max_rpm = self.get_fan_speed()
        self.config["fan_max"] = max_rpm
        self.save_config()
        try:
            if prev_enable:
                self.write_sys_file(self.pwm1_enable_path, prev_enable)
            if prev_pwm and str(prev_enable).strip() == "1":
                self.write_sys_file(self.pwm1_path, prev_pwm)
        except Exception as e:
            print(f"Error restoring fan state: {e}")
        return max_rpm

    def _patch_driver_source(self, fan_max):
        orig_file = DRIVER_BUILD_DIR / "hp-wmi.c.orig"
        target_file = DRIVER_BUILD_DIR / "hp-wmi.c"
        if not orig_file.exists():
            if target_file.exists():
                shutil.copy(target_file, orig_file)
            else:
                return False, "Error: hp-wmi.c not found."
        with open(orig_file, "r") as f:
            content = f.read()
        max_rpm_val = math.floor(fan_max / 100)
        content = content.replace("#define OMEN_MAX_RPM 60", f"#define OMEN_MAX_RPM {max_rpm_val}")
        if self.config.get("enable_experimental", False):
            board_name = self.config.get("cached_board_name") or self.check_board_support()[1]
            if board_name and board_name != "Unknown":
                profile = self.config.get("thermal_profile", "omen")
                target_array = {"victus": "victus_thermal_profile_boards", "victus_s": "victus_s_thermal_profile_boards"}.get(profile, "omen_thermal_profile_boards")
                start_idx = content.find(f"{target_array}[]")
                if start_idx != -1:
                    end_idx = content.find("};", start_idx)
                    if end_idx != -1:
                        segment = content[start_idx:end_idx]
                        if f'"{board_name}"' not in segment:
                            if target_array == "victus_s_thermal_profile_boards":
                                insertion = (
                                    '        {\n            .matches = {DMI_MATCH(DMI_BOARD_NAME, "%s")},\n'
                                    '            .driver_data = (void *)&victus_s_thermal_params,\n        },\n'
                                ) % board_name
                            else:
                                insertion = f'\t"{board_name}",\n'
                            content = content[:end_idx] + insertion + content[end_idx:]
        with open(target_file, "w") as f:
            f.write(content)
        return True, "Patch applied successfully."

    def install_driver_temp(self, force=False):
        if self.pwm1_path and self.pwm1_path.exists():
            if not force and not self.config.get("bypass_patch_warning", False):
                return False, "PWM_DETECTED"
        fan_max = self.config.get("fan_max", 0)
        if fan_max == 0:
            return False, "Error: Please calibrate first to get Max RPM."
        success, msg = self._patch_driver_source(fan_max)
        if not success:
            return False, msg
        try:
            subprocess.run(["make"], check=True, cwd=DRIVER_BUILD_DIR, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, f"Make failed: {e.stderr}"
        ko_files = list(DRIVER_BUILD_DIR.glob("*.ko"))
        if not ko_files:
            return False, "Error: No .ko file found after make."
        subprocess.run(["modprobe", "-r", "hp-wmi"], check=False)
        try:
            subprocess.run(["modprobe", "sparse_keymap"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, f"Modprobe sparse_keymap failed: {e.stderr}"
        try:
            subprocess.run(["insmod", str(ko_files[0])], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            subprocess.run(["modprobe", "hp-wmi"], check=False)
            return False, f"Insmod failed: {e.stderr}\n(Original driver re-loaded attempts)"
        subprocess.run(["make", "clean"], check=True, cwd=DRIVER_BUILD_DIR)
        self.config["install_type"] = "temporary"
        self.save_config()
        return True, "Temporary driver installed successfully."

    def install_driver_perm(self, force=False):
        if self.pwm1_path and self.pwm1_path.exists():
            if not force and not self.config.get("bypass_patch_warning", False):
                return False, "PWM_DETECTED"
        fan_max = self.config.get("fan_max", 0)
        if fan_max == 0:
            return False, "Error: Please calibrate first to get Max RPM."
        success, msg = self._patch_driver_source(fan_max)
        if not success:
            return False, msg
        try:
            subprocess.run(["/bin/bash", "install_driver.sh"], cwd=OMEN_FAN_DIR, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, f"Install script failed: {e.stderr}"
        self.config["install_type"] = "permanent"
        self.save_config()
        return True, "Permanent driver installed successfully."

    def check_install_type(self):
        if not (self.pwm1_path and self.pwm1_path.exists()):
            return None
        conf_type = self.config.get("install_type")
        if conf_type in ("permanent", "temporary"):
            return conf_type
        try:
            kernel_ver = subprocess.check_output(["uname", "-r"]).decode().strip()
            hp_driver_dir = Path(f"/lib/modules/{kernel_ver}/kernel/drivers/platform/x86/hp")
            if hp_driver_dir.exists() and list(hp_driver_dir.glob("*.bak")):
                return "permanent"
        except Exception:
            pass
        return "temporary"

    def start_stress_test(self, duration_sec, core_count=None):
        import sys as _sys
        core_count = core_count or os.cpu_count() or 4
        self.stop_stress_test()
        self.stress_processes = []
        cmd = [_sys.executable, "-c", "while True: 9999**9999"]
        try:
            for _ in range(core_count):
                self.stress_processes.append(subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
            return True
        except Exception as e:
            print(f"Error starting stress test: {e}")
            self.stop_stress_test()
            return False

    def stop_stress_test(self):
        if not getattr(self, "stress_processes", None):
            return
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

    def set_bios_control(self, enabled):
        try:
            subprocess.run(["modprobe", "ec_sys", "write_support=1"], check=True)
        except Exception as e:
            print(f"Failed to load ec_sys: {e}")
            return False
        ECIO_FILE = "/sys/kernel/debug/ec/ec0/io"
        try:
            with open(ECIO_FILE, "r+b") as ec:
                if not enabled:
                    ec.seek(98)
                    ec.write(bytes([6]))
                    time.sleep(0.1)
                    ec.seek(99)
                    ec.write(bytes([0]))
                else:
                    ec.seek(98)
                    ec.write(bytes([0]))
                    ec.seek(52)
                    ec.write(bytes([0]))
                    ec.seek(53)
                    ec.write(bytes([0]))
            return True
        except Exception as e:
            print(f"Error setting BIOS control: {e}")
            return False

    def create_service(self):
        """Creates and enables systemd service using packaged unit template (placeholder @EXECSTART@)."""
        unit_lib = Path("/usr/lib/systemd/system/omen-fan-control.service")
        unit_etc = Path("/etc/systemd/system/omen-fan-control.service")
        try:
            if unit_lib.exists():
                # Package-installed unit: just enable and start, do not overwrite
                subprocess.run(["systemctl", "daemon-reload"], check=True)
                subprocess.run(["systemctl", "enable", "omen-fan-control.service"], check=True)
                subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
                return True, "Service enabled and started."
            template_path = Path(__file__).parent / "data" / "omen-fan-control.service"
            if not template_path.exists():
                return False, f"Service template not found: {template_path}"
            exec_start = f"{sys.executable} -m omen_fan_control.cli serve"
            service_content = template_path.read_text().replace("@EXECSTART@", exec_start)
            with open(unit_etc, "w") as f:
                f.write(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "omen-fan-control.service"], check=True)
            subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service created and started."
        except Exception as e:
            return False, f"Failed to create service: {e}"

    def remove_service(self):
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-control.service"], check=False)
            subprocess.run(["systemctl", "disable", "omen-fan-control.service"], check=False)
            unit_etc = Path("/etc/systemd/system/omen-fan-control.service")
            if unit_etc.exists():
                unit_etc.unlink()
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            return True, "Service removed."
        except Exception as e:
            return False, f"Failed to remove service: {e}"

    def restart_service(self):
        """Restart the systemd service."""
        try:
            subprocess.run(["systemctl", "restart", "omen-fan-control.service"], check=True)
            return True, "Service restarted."
        except Exception as e:
            return False, f"Failed to restart service: {e}"

    def is_service_installed(self):
        return (
            Path("/etc/systemd/system/omen-fan-control.service").exists()
            or Path("/usr/lib/systemd/system/omen-fan-control.service").exists()
        )

    def is_service_running(self):
        try:
            res = subprocess.run(["systemctl", "is-active", "omen-fan-control.service"], capture_output=True, text=True)
            return res.stdout.strip() == "active"
        except Exception:
            return False

    def restore_driver(self):
        messages = []
        dkms_name, dkms_version = "hp-wmi-omen", "1.0"
        try:
            try:
                result = subprocess.run(["dkms", "status"], capture_output=True, text=True)
                if dkms_name in result.stdout:
                    subprocess.run(["dkms", "remove", f"{dkms_name}/{dkms_version}", "--all"], check=False)
                    messages.append("Removed DKMS module.")
            except FileNotFoundError:
                pass
            for d in [Path(f"/usr/src/{dkms_name}-{dkms_version}"), Path(f"/usr/src/{dkms_name}")]:
                if d.exists() and dkms_name in str(d):
                    subprocess.run(["rm", "-rf", str(d)], check=False)
            for hook in ["/etc/pacman.d/hooks/90-hp-wmi-omen.hook", "/etc/kernel/postinst.d/zz-hp-wmi-omen", "/etc/kernel/install.d/99-hp-wmi-omen.install"]:
                if Path(hook).exists():
                    Path(hook).unlink()
                    messages.append(f"Removed hook: {Path(hook).name}")
            kernel_ver = subprocess.check_output(["uname", "-r"]).decode().strip()
            restored_count = 0
            for search_dir in [Path(f"/lib/modules/{kernel_ver}/kernel/drivers/platform/x86/hp"), Path(f"/lib/modules/{kernel_ver}/updates")]:
                if search_dir.exists():
                    for bak_file in search_dir.rglob("*.bak"):
                        target = bak_file.parent / bak_file.stem
                        subprocess.run(["mv", str(bak_file), str(target)], check=True)
                        restored_count += 1
            if restored_count == 0 and not messages:
                if self.config.get("install_type") == "temporary":
                    subprocess.run(["modprobe", "-r", "hp-wmi"], check=False)
                    subprocess.run(["modprobe", "hp-wmi"], check=False)
                    self.config.pop("install_type", None)
                    self.save_config()
                    return True, "Temporary driver unloaded. (No backups needed)"
                return False, "No backup files (.bak) found to restore."
            subprocess.run(["depmod", "-a"], check=True)
            subprocess.run(["modprobe", "-r", "hp-wmi"], check=False)
            subprocess.run(["modprobe", "hp-wmi"], check=True)
            self.config.pop("install_type", None)
            self.save_config()
            if restored_count > 0:
                messages.append(f"Restored {restored_count} driver backup(s).")
            messages.append("Driver reloaded.")
            return True, " ".join(messages)
        except subprocess.CalledProcessError as e:
            return False, f"Error restoring driver: {e}"
        except Exception as e:
            return False, f"Error: {e}"