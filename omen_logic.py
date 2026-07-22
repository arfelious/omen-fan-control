import os
# Omen Fan Control
# Control your HP Laptop's fans in Linux
# Copyright (C) 2026 arfelious
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import glob
import gzip
import json
import time
import math
import shutil
import subprocess
import threading
import re
from pathlib import Path
import struct

# Constants
HWMON_PATH_PATTERN = "/sys/devices/platform/hp-wmi/hwmon/*/"
THERMAL_ZONE_PATH = "/sys/class/thermal/thermal_zone0/temp"
LOG_LEVELS = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "QUIET": 4,
}
# Determine config path based on permissions
if os.geteuid() == 0:
    CONFIG_DIR = Path("/etc/omen-fan-control")
else:
    CONFIG_DIR = Path(os.path.expanduser("~/.config/omen-fan-control"))

CONFIG_FILE = CONFIG_DIR / "config.json"
VOLATILE_CONFIG_DIR = Path("/run/omen-fan-control")
VOLATILE_CONFIG_FILE = VOLATILE_CONFIG_DIR / "config.json"

DEFAULT_CALIBRATION_WAIT = 30
DEFAULT_WATCHDOG_INTERVAL = 90
OMEN_FAN_DIR = Path(__file__).parent.absolute()
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
    "8A15", "8A42", "8BAD", "8E41", "8D2F",
    
    "88F8", "8A25",
    "8BAB", "8BBE", "8BCA", "8BD4", "8BD5", "8C76", "8C77", "8C78", "8BCD",
    "8C4D", "8C99", "8C9C", "8D26", "8D41", "8D87", "8A44", "8A4D", "8C58", "8BA9", "8BAA"
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
    "8A44", "8BA8", "8BA9", "8BAA", "8BAC", "8C76", "8C77", "8C78",
    "8BCA", "8BCB", "8BCF", "8C9B", "8BB3", "8BB4", "8C4E",
    "8C58", "8C75", "8C74", "8C73", "8CC1", "8CC0", "8CF1", "8CF2", "8CF3",
    "8CF4", "8D2F"
}

class FanController:
    def __init__(self, config_path=None):
        self._find_paths()
        if config_path:
            self.config_path = Path(config_path)
        else:
            self.config_path = CONFIG_FILE
            
        self.config = self.load_config()

        # Recover from interrupted/stale fan cleaner cycle on startup
        if self.config.get("cleaner_in_progress", False):
            start_ts = self.config.get("cleaner_start_time", 0)
            if not start_ts or (time.time() - start_ts >= 30):
                self.emergency_stop_fan_cleaning()

    def check_board_support(self):
        """
        Checks if the current board is in the supported list.
        Returns (status, board_name)
        status: "SUPPORTED", "POSSIBLY_SUPPORTED", "UNSUPPORTED"
        """
        # Return cached if available
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
        elif board_name in POSSIBLY_SUPPPORTED_OMEN_BOARDS:
            return "POSSIBLY_SUPPORTED", board_name
        else:
            return "UNSUPPORTED", board_name

    def _find_paths(self):
        """Finds the correct hwmon paths for fan control."""
        # Find CPU temp path independent of HP WMI
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
        self.fan2_input_path = self.hwmon_path / "fan2_input"
        self.cpu_temp_path = self._find_cpu_temp_path()

    def _find_cpu_temp_path(self):
        """Finds the CPU temperature input file."""
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
        
        # Fallback to thermal_zone0
        if Path("/sys/class/thermal/thermal_zone0/temp").exists():
             return Path("/sys/class/thermal/thermal_zone0/temp")
             
        return None


    def load_config(self):
        """Loads configuration from JSON files. Merges based on last modified date."""
        defaults = {
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
            "reference_sensor": "cpu"
        }
        
        config = defaults.copy()
        
        p_data = {}
        p_time = 0
        if self.config_path.exists():
            try:
                p_time = self.config_path.stat().st_mtime
                with open(self.config_path, "r") as f:
                    p_data = json.load(f)
            except Exception as e:
                print(f"Error loading persistent config: {e}")

        v_data = {}
        v_time = 0
        if VOLATILE_CONFIG_FILE.exists():
            try:
                v_time = VOLATILE_CONFIG_FILE.stat().st_mtime
                with open(VOLATILE_CONFIG_FILE, "r") as f:
                    v_data = json.load(f)
            except Exception as e:
                print(f"Error loading volatile config: {e}")

        # Apply older config first, then newer config second (so it overrides)
        if p_time <= v_time:
            config.update(p_data)
            config.update(v_data)
        else:
            config.update(v_data)
            config.update(p_data)
                
        return config

    def save_config(self, volatile=False, source=None):
        """Saves current configuration to JSON file. Use volatile=True for /run."""
        target_path = VOLATILE_CONFIG_FILE if volatile else self.config_path
        
        if target_path.parent:
             target_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.config["version"] = CONFIG_VERSION
        if source:
            self.config["config_source"] = source
            
        with open(target_path, "w") as f:
            json.dump(self.config, f, indent=4)
            f.flush()
            try:
                import os
                os.fsync(f.fileno())
            except:
                pass

    def write_sys_file(self, path, value):
        """Helper to write to sysfs files."""
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
        """Helper to read from sysfs files."""
        if not path or not path.exists():
            return None
        try:
            with open(path, "r") as f:
                return f.read().strip()
        except Exception as e:
            print(f"Error reading {path}: {e}")
            return None

    def parse_hwmon_rpm(self, val):
        """Parses hwmon fan input value, handling hp-wmi bit 7 reverse flag (12800 RPM = 0 RPM reverse, 16500 RPM = 3700 RPM reverse)."""
        if not val:
            return 0, False
        try:
            raw_rpm = int(val)
            # If hp-wmi reports raw speed with bit 7 set (value >= 12800)
            if raw_rpm >= 12800:
                reverse_bit_speed = raw_rpm // 100
                actual_speed = (reverse_bit_speed & 0x7F) * 100
                return actual_speed, True
            else:
                return raw_rpm, False
        except Exception:
            return 0, False

    def get_fan_speed(self):
        """Returns current fan speed in RPM, decoding hp-wmi reverse bit offsets cleanly."""
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

    def get_fan_speed_info(self):
        """Returns (rpm, is_reverse) tuple, combining hwmon bit 7 detection and active cleaner state."""
        val1 = self.read_sys_file(self.fan1_input_path)
        val2 = self.read_sys_file(self.fan2_input_path)
        
        rpm1, is_rev1 = self.parse_hwmon_rpm(val1)
        rpm2, is_rev2 = self.parse_hwmon_rpm(val2)

        is_reverse = is_rev1 or is_rev2 or self.config.get("cleaner_in_progress", False)
        return max(rpm1, rpm2), is_reverse

    def get_cpu_temp(self):
        """Returns CPU temp in Celsius."""
        if self.cpu_temp_path:
            val = self.read_sys_file(self.cpu_temp_path)
            return int(val) // 1000 if val else 0
        return 0

    def has_gpu(self):
        """Checks if an NVIDIA or AMD GPU is present."""
        if hasattr(self, "_has_gpu_cache"):
            return self._has_gpu_cache
        
        self._has_gpu_cache = self.get_gpu_temp() > 0
        return self._has_gpu_cache

    def get_gpu_temp(self):
        """Returns GPU temp in Celsius for NVIDIA or AMD."""
        # 1. Try NVIDIA (nvidia-smi is most reliable)
        try:
            res = subprocess.run(["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"], 
                                 capture_output=True, text=True)
            if res.returncode == 0 and res.stdout.strip():
                return int(res.stdout.strip())
        except:
            pass

        # 2. Try AMD (Look for amdgpu hwmon)
        try:
            for hwmon in Path("/sys/class/hwmon").glob("hwmon*"):
                name_path = hwmon / "name"
                if name_path.exists():
                    with open(name_path, "r") as f:
                        name = f.read().strip()
                        if "amdgpu" in name.lower():
                            # AMD usually has multiple inputs, temp1_input is usually the edge temp
                            temp_path = hwmon / "temp1_input"
                            if temp_path.exists():
                                val = self.read_sys_file(temp_path)
                                return int(val) // 1000 if val else 0
        except:
            pass

        return 0

    def get_reference_temp(self):
        """Returns the temperature of the selected reference sensor."""
        sensor = self.config.get("reference_sensor", "cpu")
        if sensor == "gpu":
            gpu_temp = self.get_gpu_temp()
            # Fallback to CPU if GPU temp is 0 (sleeping or not found)
            if gpu_temp > 0:
                return gpu_temp
        return self.get_cpu_temp()


    def get_all_core_temps(self):
        """Returns a list of tuples [(label, temp), ...] sorted by core index."""
        core_temps = []
        package_temps = []
        
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
                
                val = self.read_sys_file(f)
                if not val: continue
                temp = int(val) // 1000
                
                if "Core" in label:
                    try:
                        idx = int(label.split()[-1])
                        core_temps.append((idx, label, temp))
                    except:
                        core_temps.append((999, label, temp))
                elif "Package" in label:
                    package_temps.append((label, temp))
            except:
                continue
        
        core_temps.sort(key=lambda x: x[0])
        
        params = []
        for p in package_temps:
            params.append(p)
            
        for c in core_temps:
            params.append((c[1], c[2]))
            
        return params

    def set_fan_mode(self, mode):
        """Sets fan mode: 'max', 'auto', or 'manual'."""
        if mode == 'max':
            self.write_sys_file(self.pwm1_enable_path, 0)
        elif mode == 'auto':
            self.write_sys_file(self.pwm1_enable_path, 2)

    def set_fan_pwm(self, value):
        """Sets fan speed (0-255). Ensures manual mode (pwm1_enable=1)."""
        # Ensure we are in manual mode
        current_enable = self.read_sys_file(self.pwm1_enable_path)
        if current_enable != "1":
            self.write_sys_file(self.pwm1_enable_path, 1)
            
        # value should be 0-255
        self.write_sys_file(self.pwm1_path, str(int(value)))

    def calculate_target_pwm(self, current_temp):
        """Calculates target PWM (0-255) based on curve and temperature."""
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
                p1 = curve[i]
                p2 = curve[i+1]
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

    def calibrate(self):
        """Runs calibration routine. Yields progress (0-100), returns max RPM."""
        print("Starting calibration...")
        
        try:
            prev_enable = self.read_sys_file(self.pwm1_enable_path) or "2"
            prev_pwm = self.read_sys_file(self.pwm1_path) or "0"
        except:
            prev_enable = "2"
            prev_pwm = "0"
            
        self.set_fan_mode('max')
        
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
        """Patches hp-wmi.c with the max rpm value and experimental boards if enabled."""
        orig_file = OMEN_FAN_DIR / "hp-wmi.c.orig"
        target_file = OMEN_FAN_DIR / "hp-wmi.c"
        
        if not orig_file.exists():
            if target_file.exists():
                shutil.copy(target_file, orig_file)
            else:
                return False, "Error: hp-wmi.c not found."

        # Read orig content
        with open(orig_file, "r") as f:
            content = f.read()

        # 1. Patch Max RPM
        max_rpm_val = math.floor(fan_max / 100)
        new_define = f"#define OMEN_MAX_RPM {max_rpm_val}"
        content = content.replace("#define OMEN_MAX_RPM 60", new_define)
        
        # 2. Patch Experimental Support if enabled
        if self.config.get("enable_experimental", False):
            board_name = self.config.get("cached_board_name")
            if not board_name:
                 # Try to get it if not cached
                 _, board_name = self.check_board_support()
            
            if board_name and board_name != "Unknown":
                profile = self.config.get("thermal_profile", "omen")
                
                target_array = "omen_thermal_profile_boards"
                params_struct = "victus_s_thermal_params" # Default
                
                if profile == "victus":
                    target_array = "victus_thermal_profile_boards"
                elif profile in ["victus_s", "omen_v1", "omen_v1_legacy", "omen_v1_no_ec"]:
                    target_array = "victus_s_thermal_profile_boards"
                    if profile == "omen_v1":
                        params_struct = "omen_v1_thermal_params"
                    elif profile == "omen_v1_legacy":
                        params_struct = "omen_v1_legacy_thermal_params"
                    elif profile == "omen_v1_no_ec":
                        params_struct = "omen_v1_no_ec_thermal_params"
                           
                start_idx = content.find(f"{target_array}[]")
                if start_idx != -1:
                    # Find closing brace after start_idx
                    end_idx = content.find("};", start_idx)
                    if end_idx != -1:
                         # Check if board is already in there
                         segment = content[start_idx:end_idx]
                         if f'"{board_name}"' not in segment:
                             if target_array == "victus_s_thermal_profile_boards":
                                 # Find sentinel {} and insert BEFORE it
                                 sentinel_idx = content.find("{},", start_idx)
                                 if sentinel_idx == -1 or sentinel_idx > end_idx:
                                      sentinel_idx = content.find("{}", start_idx)
                                      
                                 if sentinel_idx != -1 and sentinel_idx < end_idx:
                                     insertion = f'        {{\n            .matches = {{DMI_MATCH(DMI_BOARD_NAME, "{board_name}")}},\n            .driver_data = (void *)&{params_struct},\n        }},\n'
                                     content = content[:sentinel_idx] + insertion + content[sentinel_idx:]
                                 else:
                                     # Fallback to appending at end if no sentinel found
                                     insertion = f'        {{\n            .matches = {{DMI_MATCH(DMI_BOARD_NAME, "{board_name}")}},\n            .driver_data = (void *)&{params_struct},\n        }},\n'
                                     content = content[:end_idx] + insertion + content[end_idx:]
                             else:
                                 insertion = f'    "{board_name}",\n'
                                 content = content[:end_idx] + insertion + content[end_idx:]
                         else:
                             print(f"Board {board_name} already in {target_array} in orig file? Skipping append.")
                else:
                    print(f"Warning: Could not find array {target_array} in hp-wmi.c")

        with open(target_file, "w") as f:
            f.write(content)
            
        return True, "Patch applied successfully."

    @staticmethod
    def _format_make_error(stderr: str) -> str:
        """Parse make/build stderr and return a user-friendly message.

        Detects common kernel-module build failures (e.g. missing
        generated/autoconf.h on Debian) and appends actionable fix
        instructions so the user doesn't have to search the web.
        """
        hint = ""
        if "generated/autoconf.h" in stderr:
            hint = (
                "\n\n--- Likely cause ---\n"
                "Your kernel headers are incomplete (generated/autoconf.h is missing).\n"
                "This is a known issue on Debian/Ubuntu where headers are split into two packages.\n\n"
                "Fix:\n"
                "  sudo apt reinstall linux-headers-$(uname -r)\n\n"
                "Diagnostic (check if autoconf.h is present):\n"
                "  ls /usr/src/linux-headers-$(uname -r)/include/generated/"
            )
        elif "No such file or directory" in stderr and "scripts/basic/Makefile" in stderr:
            hint = (
                "\n\n--- Likely cause ---\n"
                "Kernel build scripts (kbuild) are missing.\n"
                "This is a common issue on Debian/Ubuntu where headers are split across packages.\n\n"
                "Fix:\n"
                "  Debian/Ubuntu: sudo apt install \"linux-kbuild-$(uname -r | cut -d. -f1,2,3 | cut -d+ -f1)*\"\n"
            )
        elif "No such file or directory" in stderr and "/lib/modules/" in stderr:
            hint = (
                "\n\n--- Likely cause ---\n"
                "Kernel headers not found for the running kernel.\n\n"
                "Fix:\n"
                "  Debian/Ubuntu : sudo apt install linux-headers-$(uname -r)\n"
                "  Fedora/RHEL   : sudo dnf install kernel-devel-$(uname -r)\n"
                "  Arch Linux    : sudo pacman -S linux-headers"
            )
        return f"Make failed: {stderr}{hint}"

    def install_driver_temp(self, force=False):
        """Installs driver temporarily using insmod. Requires calibration first."""
        if self.pwm1_path and self.pwm1_path.exists():
            bypass = self.config.get("bypass_patch_warning", False)
            if not force and not bypass:
                return False, "PWM_DETECTED"

        fan_max = self.get_effective_fan_max()
        if fan_max == 0:
            return False, "Error: Please calibrate or set Manual Max RPM in Options."

        success, msg = self._patch_driver_source(fan_max)
        if not success:
             return False, msg

        try:
            subprocess.run(["make"], check=True, cwd=OMEN_FAN_DIR, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, self._format_make_error(e.stderr)
        
        ko_files = list(OMEN_FAN_DIR.glob("*.ko"))
        if not ko_files:
            return False, "Error: No .ko file found after make."
        
        subprocess.run(["modprobe", "-r", "hp-wmi"], check=False)
        
        try:
            # Load dependencies that might be missing if hp-wmi was never loaded
            deps = ["wmi", "rfkill", "hwmon", "platform_profile", "sparse_keymap", "acpi_ac"]
            for dep in deps:
                subprocess.run(["modprobe", dep], check=False, capture_output=True)
            
            subprocess.run(["modprobe", "sparse_keymap"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, f"Loading dependencies failed: {e.stderr}"
        
        try:
            subprocess.run(["insmod", str(ko_files[0])], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
             subprocess.run(["modprobe", "hp-wmi"], check=False)
             return False, f"Insmod failed: {e.stderr}\n(Original driver re-loaded attempts)"
        
        # Clean up build artifacts as the driver module is now loaded into memory
        subprocess.run(["make", "clean"], cwd=OMEN_FAN_DIR, check=False, capture_output=True)

        self.config["install_type"] = "temporary"
        self.save_config()
             
        return True, "Temporary driver installed successfully."

    def install_driver_perm(self, force=False):
        """Installs driver permanently by patching and running install script."""
        if self.pwm1_path and self.pwm1_path.exists():
            bypass = self.config.get("bypass_patch_warning", False)
            if not force and not bypass:
                return False, "PWM_DETECTED"

        fan_max = self.get_effective_fan_max()
        if fan_max == 0:
            return False, "Error: Please calibrate or set Manual Max RPM in Options."

        success, msg = self._patch_driver_source(fan_max)
        if not success:
            return False, msg

        try:
            subprocess.run(["/bin/bash", "install_driver.sh"], cwd=OMEN_FAN_DIR, check=True)
        except subprocess.CalledProcessError:
            return False, "Install script failed. Check terminal output above for details."
            
        self.config["install_type"] = "permanent"
        self.save_config()
            
        return True, "Permanent driver installed successfully."

    def check_install_type(self):
        """Determines installation type: 'permanent', 'temporary', or None."""
        if not (self.pwm1_enable_path and self.pwm1_enable_path.exists()):
            return None
        
        conf_type = self.config.get("install_type")
        if conf_type in ["permanent", "temporary"]:
            return conf_type
        
        try:
            kernel_ver = subprocess.check_output(["uname", "-r"]).decode().strip()
            hp_driver_dir = Path(f"/lib/modules/{kernel_ver}/kernel/drivers/platform/x86/hp")
            
            if hp_driver_dir.exists():
                if list(hp_driver_dir.glob("*.bak")):
                    return "permanent"
        except Exception:
            pass
        
        return "temporary"

    def start_stress_test(self, duration_sec, core_count=None):
        """Starts a CPU stress test. Duration handled by caller."""
        import os
        import sys
        
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

    def stop_stress_test(self):
        """Stops the running stress test."""
        if hasattr(self, 'stress_processes') and self.stress_processes:
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
        """Enables or disables BIOS fan control by writing to EC registers."""
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

    # Service Management
    def create_service(self):
        """
        Creates and enables a systemd service to run 'omen_cli.py serve'.
        """
        import sys
        service_content = f"""[Unit]
Description=HP Omen Fan Control Service
After=multi-user.target

[Service]
Type=simple
ExecStart={sys.executable} {str(OMEN_FAN_DIR / 'omen_cli.py')} serve
WorkingDirectory={str(OMEN_FAN_DIR)}
Restart=on-failure
StartLimitBurst=5
RestartSec=5
User=root

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/omen-fan-control.service")
        
        try:
            with open("omen-fan-control.service", "w") as f:
                f.write(service_content)
                
            subprocess.run(["mv", "omen-fan-control.service", str(service_path)], check=True)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "omen-fan-control.service"], check=True)
            subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service created and started."
        except Exception as e:
            return False, f"Failed to create service: {e}"

    def remove_service(self):
        """Stops and removes the systemd service."""
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-control.service"], check=False)
            subprocess.run(["systemctl", "disable", "omen-fan-control.service"], check=False)
            
            service_path = Path("/etc/systemd/system/omen-fan-control.service")
            if service_path.exists():
                subprocess.run(["rm", str(service_path)], check=True)
                
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            return True, "Service removed."
        except Exception as e:
            return False, f"Failed to remove service: {e}"

    def restart_service(self):
        """Restarts the systemd service."""
        try:
            subprocess.run(["systemctl", "restart", "omen-fan-control.service"], check=True)
            return True, "Service restarted."
        except Exception as e:
            return False, f"Failed to restart service: {e}"

    def start_service(self):
        """Starts the systemd service."""
        try:
            subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service started."
        except Exception as e:
            return False, f"Failed to start service: {e}"

    def stop_service(self):
        """Stops the systemd service."""
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-control.service"], check=True)
            return True, "Service stopped."
        except Exception as e:
            return False, f"Failed to stop service: {e}"

    def is_service_installed(self):
        """Checks if service file exists."""
        return Path("/etc/systemd/system/omen-fan-control.service").exists()

    def is_service_running(self):
        """Checks if service is actively running."""
        try:
            # Check active state
            res = subprocess.run(["systemctl", "is-active", "omen-fan-control.service"], capture_output=True, text=True)
            return res.stdout.strip() == "active"
        except Exception:
            return False

    def create_shutdown_service(self):
        """
        Creates and enables a systemd service to run as a shutdown hook.
        Sets fans to 30% on shutdown/reboot.
        """
        import sys
        service_content = f"""[Unit]
Description=HP Omen Fan Control Shutdown Hook
DefaultDependencies=no
Before=shutdown.target reboot.target halt.target

[Service]
Type=oneshot
ExecStart=/usr/bin/true
ExecStop={sys.executable} {str(OMEN_FAN_DIR / 'omen_cli.py')} fan-control --mode manual --value 30% --no-save --source shutdown-hook
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/omen-fan-shutdown.service")
        
        try:
            with open("omen-fan-shutdown.service", "w") as f:
                f.write(service_content)
                
            subprocess.run(["mv", "omen-fan-shutdown.service", str(service_path)], check=True)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "omen-fan-shutdown.service"], check=True)
            subprocess.run(["systemctl", "start", "omen-fan-shutdown.service"], check=True)
            
            self.config["shutdown_hook_enabled"] = True
            self.save_config()
            
            return True, f"Shutdown hook service created at {service_path} and enabled."
        except Exception as e:
            return False, f"Failed to create shutdown hook: {e}"

    def remove_shutdown_service(self):
        """Stops and removes the shutdown hook service."""
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-shutdown.service"], check=False)
            subprocess.run(["systemctl", "disable", "omen-fan-shutdown.service"], check=False)
            
            service_path = Path("/etc/systemd/system/omen-fan-shutdown.service")
            if service_path.exists():
                subprocess.run(["rm", str(service_path)], check=True)
                
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            
            # Smart Cleanup: Remove volatile config if it was created by us
            if VOLATILE_CONFIG_FILE.exists():
                try:
                    with open(VOLATILE_CONFIG_FILE, "r") as f:
                        v_data = json.load(f)
                    if v_data.get("config_source") == "shutdown-hook":
                        VOLATILE_CONFIG_FILE.unlink()
                        print(f"Cleaned up shutdown-hook config at {VOLATILE_CONFIG_FILE}")
                except:
                    pass

            self.config["shutdown_hook_enabled"] = False
            self.save_config()
            
            return True, f"Shutdown hook service removed from {service_path}."
        except Exception as e:
            return False, f"Failed to remove shutdown hook: {e}"

    def is_shutdown_service_enabled(self):
        """Checks if shutdown hook service is enabled."""
        return Path("/etc/systemd/system/omen-fan-shutdown.service").exists()

    def restore_driver(self):
        """Restores the original driver from backup files and removes DKMS/hooks."""
        messages = []
        
        try:
            # 1. Remove DKMS module if installed
            dkms_name = "hp-wmi-omen"
            dkms_version = "1.0"
            try:
                result = subprocess.run(["dkms", "status"], capture_output=True, text=True)
                if dkms_name in result.stdout:
                    subprocess.run(["dkms", "remove", f"{dkms_name}/{dkms_version}", "--all"], check=False)
                    messages.append("Removed DKMS module.")
            except FileNotFoundError:
                pass  # DKMS not installed
            
            # 2. Remove DKMS source directory
            dkms_src = Path(f"/usr/src/{dkms_name}-{dkms_version}")
            if dkms_src.exists() and dkms_name in str(dkms_src) and len(str(dkms_src)) > 10:
                subprocess.run(["rm", "-rf", str(dkms_src)], check=False)
            
            # 3. Remove our kernel hooks source
            hook_src = Path(f"/usr/src/{dkms_name}")
            if hook_src.exists() and dkms_name in str(hook_src) and len(str(hook_src)) > 10:
                subprocess.run(["rm", "-rf", str(hook_src)], check=False)
            
            # 4. Remove distro-specific kernel hooks
            hook_paths = [
                "/etc/pacman.d/hooks/90-hp-wmi-omen.hook",  # Arch
                "/etc/kernel/postinst.d/zz-hp-wmi-omen",   # Debian/Ubuntu
                "/etc/kernel/install.d/99-hp-wmi-omen.install",  # Fedora
            ]
            for hook in hook_paths:
                if Path(hook).exists():
                    subprocess.run(["rm", hook], check=False)
                    messages.append(f"Removed hook: {Path(hook).name}")
            
            # 5. Restore backup files
            kernel_ver = subprocess.check_output(["uname", "-r"]).decode().strip()
            search_paths = [
                Path(f"/lib/modules/{kernel_ver}/kernel/drivers/platform/x86/hp"),
                Path(f"/lib/modules/{kernel_ver}/updates")
            ]
            
            restored_count = 0
            
            for search_dir in search_paths:
                if search_dir.exists():
                    for bak_file in search_dir.rglob("*.bak"): # Recursive search for updates dir
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
            
            return True, " ".join(messages)
            
        except subprocess.CalledProcessError as e:
            return False, f"Error restoring driver: {e}"
        except Exception as e:
            return False, f"Error: {e}"

    # ---------------------------------------------------------------------------
    # Fan Cleaner WMI/ACPI Call Methods & Logging
    # ---------------------------------------------------------------------------
    def log(self, level, message):
        """Structured logger enforcing application log_level verbosity filtering."""
        target_level_name = str(self.config.get("log_level", "INFO")).upper()
        target_level = LOG_LEVELS.get(target_level_name, 1)
        msg_level = LOG_LEVELS.get(str(level).upper(), 1)

        if msg_level >= target_level and target_level < LOG_LEVELS["QUIET"]:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
            formatted = f"[{timestamp}] [{level.upper():7s}] {message}"
            print(formatted)

            try:
                log_dir = VOLATILE_CONFIG_DIR if os.access(VOLATILE_CONFIG_DIR, os.W_OK) else CONFIG_DIR
                log_dir.mkdir(parents=True, exist_ok=True)
                with open(log_dir / "app.log", "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

    def log_debug(self, msg): self.log("DEBUG", msg)
    def log_info(self, msg): self.log("INFO", msg)
    def log_warning(self, msg): self.log("WARNING", msg)
    def log_error(self, msg): self.log("ERROR", msg)

    def log_cleaner(self, message, level="DEBUG"):
        """Logs cleaner events to console and persistent log file for diagnostic visibility."""
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        formatted = f"[{timestamp}] [CLEANER] {message}"
        
        target_level = LOG_LEVELS.get(str(self.config.get("log_level", "DEBUG")).upper(), 1)
        msg_level = LOG_LEVELS.get(str(level).upper(), 1)
        if msg_level >= target_level and target_level < LOG_LEVELS["QUIET"]:
            print(formatted)

        try:
            log_dir = VOLATILE_CONFIG_DIR if os.access(VOLATILE_CONFIG_DIR, os.W_OK) else CONFIG_DIR
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "cleaner.log"
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(formatted + "\n")
        except Exception:
            pass

    def get_cleaner_logs(self, max_lines=60):
        """Reads recent cleaner logs."""
        for log_dir in [VOLATILE_CONFIG_DIR, CONFIG_DIR]:
            log_file = log_dir / "cleaner.log"
            if log_file.exists():
                try:
                    with open(log_file, "r") as f:
                        lines = f.readlines()
                        return "".join(lines[-max_lines:])
                except Exception as e:
                    return f"Error reading logs: {e}"
        return "No cleaner logs found yet."

    def cleaner_acpi_call(self, method_id, command, command_type, data_size, payload_bytes):
        """Formulates a binary WMI payload, encodes it to hex, writes to acpi_call, and reads response."""
        if not os.path.exists("/proc/acpi/call"):
            self.log_cleaner("ERROR: /proc/acpi/call does not exist! acpi_call module not loaded.")
            raise FileNotFoundError("acpi_call kernel module is not loaded (missing /proc/acpi/call).")
        
        # 16-byte header: Signature ("SECU"), Command (u32), CommandType (u32), Size (u32)
        header = struct.pack("<4sIII", b"SECU", command, command_type, data_size)
        
        payload = bytearray(data_size)
        for i, val in enumerate(payload_bytes):
            if i < data_size:
                payload[i] = val
                
        full_buffer = header + payload
        hex_arg = f"b{full_buffer.hex()}"
        
        acpi_cmd = f"\\_SB.WMID.WMAA 0 {method_id} {hex_arg}"
        preview_bytes = list(payload_bytes[:4]) if payload_bytes else []
        self.log_cleaner(f"ACPI WRITE -> Method:{method_id} Cmd:{command} Type:{command_type} Size:{data_size} Payload[0..3]:{preview_bytes}")
        
        try:
            with open("/proc/acpi/call", "w") as f:
                f.write(acpi_cmd)
            with open("/proc/acpi/call", "r") as f:
                response = f.read().strip()
            self.log_cleaner(f"ACPI RESP  -> {response[:100]}...")
            return response
        except PermissionError as pe:
            self.log_cleaner(f"PERMISSION ERROR -> Must run as root to write to /proc/acpi/call: {pe}")
            raise PermissionError("Must run as root to write to /proc/acpi/call.")
        except Exception as e:
            self.log_cleaner(f"ACPI ERROR -> {e}")
            raise

    def cleaner_parse_response(self, response):
        """Parses the acpi_call response buffer (handles hex arrays, null bytes, continuous hex, etc.)."""
        if not response or response.startswith("Error"):
            self.log_cleaner(f"PARSE FAIL -> Response raw: {response}")
            return False, response, []
        
        # Strip null bytes, brackets, and outer whitespace
        clean_resp = response.replace("\x00", "").replace("{", "").replace("}", "").strip()
        if not clean_resp:
            self.log_cleaner("PARSE FAIL -> Empty response buffer")
            return False, "Empty response", []

        try:
            # 1. Check for 0xXX formatted byte array (e.g. {0x50, 0x41, 0x53, 0x53, ...})
            hex_tokens = re.findall(r'0x[0-9a-fA-F]+', clean_resp)
            if hex_tokens:
                byte_vals = [int(tok, 16) & 0xFF for tok in hex_tokens]
                resp_bytes = bytes(byte_vals)
            else:
                # 2. Continuous hex string (e.g. 5041535300000000...)
                raw_hex = re.sub(r'[^0-9a-fA-F]', '', clean_resp)
                if len(raw_hex) % 2 != 0:
                    raw_hex = raw_hex[:-1]
                resp_bytes = bytes.fromhex(raw_hex)

            if len(resp_bytes) < 8:
                self.log_cleaner(f"PARSE FAIL -> Response too short ({len(resp_bytes)} bytes)")
                return False, "Response too short", list(resp_bytes)

            ret_code = struct.unpack("<I", resp_bytes[4:8])[0]
            sig = resp_bytes[0:4].decode('ascii', errors='ignore')
            data_payload = list(resp_bytes[8:])
            preview_data = data_payload[:12] if data_payload else []
            self.log_cleaner(f"PARSED RESP -> Sig:'{sig}' Code:{ret_code} Data[0..11]:{preview_data}")
            return True, {"sig": sig, "code": ret_code}, data_payload

        except Exception as e:
            self.log_cleaner(f"PARSE ERROR -> {e} (raw: {repr(response[:60])})")
            return False, f"Failed to parse response: {e}", []

    def detect_cleaner_capabilities(self):
        """Queries WMI capabilities for CleanCreek."""
        modern_supported = False
        cpu_ok, gpu_ok, fan3_ok = False, False, False
        cpu_speed, gpu_speed, fan3_speed = 33, 0, 0
        try:
            raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
            success, info, data = self.cleaner_parse_response(raw_resp)
            if success and info["sig"] == "PASS" and info["code"] == 0:
                if len(data) > 8:
                    cap_byte = data[8]
                    cpu_ok = bool(cap_byte & 1)
                    gpu_ok = bool(cap_byte & 2)
                    fan3_ok = bool(cap_byte & 4)
                    cpu_speed = data[0] & 0x7F
                    gpu_speed = data[1] & 0x7F
                    fan3_speed = data[2] & 0x7F
                    if cpu_ok or gpu_ok or fan3_ok:
                        modern_supported = True
        except Exception:
            pass

        legacy_supported = False
        try:
            raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
            success, info, data = self.cleaner_parse_response(raw_resp)
            if success and info["code"] == 0:
                if len(data) > 0 and (data[0] & 0x20):
                    legacy_supported = True
        except Exception:
            pass

        res = {
            "modern": {
                "supported": modern_supported,
                "cpu": cpu_ok,
                "gpu": gpu_ok,
                "fan3": fan3_ok,
                "cpu_speed": cpu_speed,
                "gpu_speed": gpu_speed,
                "fan3_speed": fan3_speed
            },
            "legacy": legacy_supported
        }
        self.log_cleaner(f"CAPABILITIES RESULT -> {res}")
        return res

    def check_cleaner_auto_stop(self):
        """Checks if fan cleaner cycle duration (30 seconds) has elapsed and auto-stops if needed."""
        if self.config.get("cleaner_in_progress", False):
            start_ts = self.config.get("cleaner_start_time")
            if start_ts and (time.time() - start_ts >= 30):
                self.stop_fan_cleaning()
                return True
        return False

    def is_reverse_mode_active(self):
        """Checks if the hardware is currently in fan cleaner (reverse) mode."""
        self.check_cleaner_auto_stop()

        # 1. Primary: check software cleaner state
        if self.config.get("cleaner_in_progress", False):
            return True

        # 2. Hardware check: hp-wmi sysfs fan input offset (bit 7 set >= 12800 RPM)
        try:
            val1 = self.read_sys_file(self.fan1_input_path)
            val2 = self.read_sys_file(self.fan2_input_path)
            if (val1 and int(val1) >= 12800) or (val2 and int(val2) >= 12800):
                return True
        except Exception:
            pass

        return False


    def start_fan_cleaning(self, speed=None):
        """Starts the fan cleaner sequence."""
        self.log_cleaner(f"START REQUESTED -> speed parameter: {speed}")
        
        # Check if a cleaner cycle is already active or transitioning
        if self.config.get("cleaner_in_progress", False) or self.config.get("cleaner_transitioning", False):
            self.log_cleaner("START REJECTED -> Fan cleaning cycle is already in progress.")
            return False, "Fan cleaning cycle is already in progress."

        # 1. Temperature guard check
        temp = self.get_reference_temp()
        if temp is not None and temp > 70:
            self.log_cleaner(f"START ABORTED -> Temperature too high ({temp}°C > 70°C)")
            return False, f"Temperature too high ({temp}°C > 70°C). Cannot start fan cleaning."

        # Detect capabilities
        caps = self.detect_cleaner_capabilities()
        mode = "modern" if caps["modern"]["supported"] else ("legacy" if caps["legacy"] else "modern")
        self.log_cleaner(f"CHOSEN CLEANER MODE -> {mode.upper()}")
        
        # Back up original mode
        orig_mode = self.config.get("mode", "auto")
        orig_manual = self.config.get("manual_pwm", -1)
        
        # Flag transition state; keep cleaner_in_progress False during forward coast-down
        self.config["cleaner_in_progress"] = False
        self.config["cleaner_transitioning"] = True
        self.config["cleaner_start_time"] = None
        self.config["cleaner_orig_mode"] = orig_mode
        self.config["cleaner_orig_manual"] = orig_manual
        self.config["cleaner_mode"] = mode
        
        # Save to both persistent and volatile config so service daemon sees it instantly
        self.save_config()
        self.save_config(volatile=True)

        try:
            if mode == "legacy":
                self.log_cleaner("EXECUTING LEGACY START SEQUENCE...")
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and info["code"] == 0:
                    buf = data[:4]
                    buf[3] |= 0x82
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
                    self.config["cleaner_in_progress"] = True
                    self.config["cleaner_transitioning"] = False
                    self.config["cleaner_start_time"] = time.time()
                    self.save_config()
                    self.save_config(volatile=True)
                    self.log_cleaner("LEGACY REVERSE MODE TRIGGERED SUCCESSFUL")
            else: # modern
                # Compute speeds (OMEN Gaming Hub defaults: CPU=37 / GPU=39)
                cpu_speed = caps["modern"]["cpu_speed"] if caps["modern"]["cpu_speed"] > 0 else 33
                gpu_speed = caps["modern"]["gpu_speed"] if caps["modern"]["gpu_speed"] > 0 else 0
                fan3_speed = caps["modern"]["fan3_speed"] if caps["modern"]["fan3_speed"] > 0 else 0

                if speed is None:
                    if cpu_speed == 33 or cpu_speed == 0:
                        cpu_speed = 37
                    if gpu_speed == 0:
                        gpu_speed = 39
                else:
                    s_val = int(speed)
                    if s_val > 100:
                        s_val //= 100
                    s_val = min(max(s_val, 10), 39)
                    cpu_speed = s_val
                    gpu_speed = s_val
                    fan3_speed = s_val

                self.log_cleaner(f"EXECUTING MODERN REVERSE SEQUENCE -> Target Speeds: CPU={cpu_speed} ({cpu_speed*100} RPM), GPU={gpu_speed} ({gpu_speed*100} RPM)")

                # 1. Engage WMI Reverse Speed 0 [128, 128, 0] to actively brake fans down to 0 RPM
                self.log_cleaner("STEP 1: Engaging WMI Reverse Speed 0 [128, 128, 0] to brake fans down to 0 RPM...")
                payload = [0] * 128
                payload[0] = 128
                payload[1] = 128
                payload[2] = 128 if caps["modern"]["fan3"] else 0
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)

                start_wait = time.time()
                while time.time() - start_wait < 4.0:
                    val1 = self.read_sys_file(self.fan1_input_path)
                    val2 = self.read_sys_file(self.fan2_input_path)
                    rpm1, is_rev1 = self.parse_hwmon_rpm(val1)
                    rpm2, is_rev2 = self.parse_hwmon_rpm(val2)

                    tag1 = f"-{rpm1}" if is_rev1 else f"{rpm1}"
                    tag2 = f"-{rpm2}" if is_rev2 else f"{rpm2}"
                    self.log_cleaner(f"STEP 1 BRAKING -> fan1={tag1} RPM, fan2={tag2} RPM")
                    if rpm1 < 300 and rpm2 < 300:
                        self.log_cleaner(f"Braked to 0 RPM (fan1={tag1}, fan2={tag2}) in {time.time()-start_wait:.1f}s")
                        break
                    time.sleep(0.3)
                time.sleep(0.3)

                # 2. Engage full reverse cleaning speeds directly (CPU=37/3700 RPM, GPU=39/3900 RPM) now that blades are stopped at 0 RPM
                cpu_val = cpu_speed + 128
                gpu_val = gpu_speed + 128
                fan3_val = (fan3_speed + 128) if caps["modern"]["fan3"] else 0
                self.log_cleaner(f"STEP 2: Sending Reverse WMI payload -> CPU:{cpu_val} (0x{cpu_val:02X}), GPU:{gpu_val} (0x{gpu_val:02X}), Fan3:{fan3_val}")
                
                # Start the active reverse timer immediately as blades leave 0 RPM and start reverse spin
                self.config["cleaner_start_time"] = time.time()
                self.config["cleaner_last_run"] = time.time()
                self.config["cleaner_in_progress"] = True
                self.config["cleaner_transitioning"] = False
                self.save_config()
                self.save_config(volatile=True)

                payload = [0] * 128
                payload[0] = cpu_val
                payload[1] = gpu_val
                payload[2] = fan3_val
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                parsed_ok, info, _ = self.cleaner_parse_response(raw_resp)
                if parsed_ok and info.get("sig") == "FAIL":
                    self.log_cleaner(f"WARNING: WMI returned FAIL on reverse payload write (code: {info.get('code')})")

                time.sleep(0.5)

                # 3. Verify reverse mode active on hardware
                rpm1, is_rev1 = self.parse_hwmon_rpm(self.read_sys_file(self.fan1_input_path))
                rpm2, is_rev2 = self.parse_hwmon_rpm(self.read_sys_file(self.fan2_input_path))
                is_rev = is_rev1 or is_rev2 or self.is_reverse_mode_active()
                self.log_cleaner(f"STEP 3: Hardware Reverse Check -> Active: {is_rev} (Fan1: {'-' if is_rev1 else ''}{rpm1} RPM, Fan2: {'-' if is_rev2 else ''}{rpm2} RPM)")

                cycle_id = time.time()
                self.config["cleaner_cycle_id"] = cycle_id

                # Spawn independent background thread to log live RPM and guarantee stop after 30s
                def _bg_auto_stop():
                    start_timer = time.time()
                    while time.time() - start_timer < 30:
                        time.sleep(3.0)
                        if not self.config.get("cleaner_in_progress", False) or self.config.get("cleaner_cycle_id") != cycle_id:
                            return
                        r1, rev1 = self.parse_hwmon_rpm(self.read_sys_file(self.fan1_input_path))
                        r2, rev2 = self.parse_hwmon_rpm(self.read_sys_file(self.fan2_input_path))
                        tag1 = f"-{r1}" if rev1 else f"{r1}"
                        tag2 = f"-{r2}" if rev2 else f"{r2}"
                        rem = max(0, int(30 - (time.time() - start_timer)))
                        self.log_cleaner(f"LIVE REVERSE STATUS ({rem}s remaining) -> Fan1: {tag1} RPM, Fan2: {tag2} RPM")

                    if self.config.get("cleaner_in_progress", False) and self.config.get("cleaner_cycle_id") == cycle_id:
                        self.log_cleaner("30-Second Auto-Stop Timer Fired -> Stopping cleaner...")
                        self.stop_fan_cleaning()

                threading.Thread(target=_bg_auto_stop, daemon=True).start()

            return True, "Fan cleaning started successfully."

        except Exception as e:
            self.log_cleaner(f"START SEQUENCE FAILED -> {e}. Rolling back to forwards mode!")
            self.emergency_stop_fan_cleaning()
            return False, f"Fan cleaning sequence failed: {e}"

    def stop_fan_cleaning(self):
        """Stops the fan cleaner sequence normally."""
        self.log_cleaner("STOP CLEANING REQUESTED")
        mode = self.config.get("cleaner_mode", "modern")
        orig_mode = self.config.get("cleaner_orig_mode", "auto")
        
        # Clear software states
        self.config["cleaner_in_progress"] = False
        self.config["cleaner_transitioning"] = False
        self.config["cleaner_last_run"] = time.time()
        self.config.pop("cleaner_start_time", None)
        self.config.pop("cleaner_cycle_id", None)
        self.config.pop("cleaner_orig_mode", None)
        self.config.pop("cleaner_orig_manual", None)
        self.config.pop("cleaner_mode", None)
        self.save_config()
        self.save_config(volatile=True)

        if mode == "legacy":
            try:
                self.log_cleaner("EXECUTING LEGACY STOP SEQUENCE...")
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and info["code"] == 0:
                    buf = data[:4]
                    buf[3] = (buf[3] | 0x02) & 0x7F
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
            except Exception as e:
                self.log_cleaner(f"LEGACY STOP ERROR -> {e}")
        else: # modern
            try:
                self.log_cleaner("EXECUTING MODERN STOP SEQUENCE...")
                caps = self.detect_cleaner_capabilities()
                fan3_supported = caps["modern"]["fan3"]
                current_speed = 37  # safe fallback
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
                q_success, q_info, q_data = self.cleaner_parse_response(raw_resp)
                if q_success and q_info.get("sig") == "PASS" and q_info.get("code") == 0 and len(q_data) > 2:
                    if q_data[0] & 0x80:
                        current_speed = q_data[0] - 128

                # 1. Decelerate smoothly in reverse all the way down to speed 0 (payload 128 = 0 RPM reverse)
                decel_steps = list(range(current_speed, 0, -5)) + [0]
                self.log_cleaner(f"Decelerating in reverse: {decel_steps}...")
                for s in decel_steps:
                    payload = [0] * 128
                    payload[0] = s + 128
                    payload[1] = s + 128
                    payload[2] = (s + 128) if fan3_supported else 0
                    self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                    time.sleep(0.15)

                # 2. Release reverse bit and set to 0 (Forward direction)
                self.log_cleaner("Releasing CleanCreek override [0, 0, 0]...")
                payload = [0] * 128
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                time.sleep(2.0)
            except Exception as e:
                self.log_cleaner(f"MODERN STOP ERROR -> {e}")

        # Restore original control mode and hardware fan state
        self.config["mode"] = orig_mode
        self.save_config()
        self.apply_post_cleaner_mode()
        self.log_cleaner(f"CLEANER STOP COMPLETE -> Restored mode: '{orig_mode}'")
        return True, "Fan cleaning stopped."

    def emergency_stop_fan_cleaning(self):
        """Immediately decelerates fans and terminates cleaning mode."""
        self.log_cleaner("EMERGENCY STOP REQUESTED!")
        mode = self.config.get("cleaner_mode", "modern")
        orig_mode = self.config.get("cleaner_orig_mode", self.config.get("mode", "auto"))

        self.config["cleaner_in_progress"] = False
        self.config["cleaner_transitioning"] = False
        self.config.pop("cleaner_start_time", None)
        self.config.pop("cleaner_cycle_id", None)
        self.config.pop("cleaner_orig_mode", None)
        self.config.pop("cleaner_orig_manual", None)
        self.config.pop("cleaner_mode", None)
        self.save_config()
        self.save_config(volatile=True)

        if mode == "modern" and os.path.exists("/proc/acpi/call"):
            try:
                caps = self.detect_cleaner_capabilities()
                fan3_supported = caps["modern"]["fan3"]
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
                success, info, data = self.cleaner_parse_response(raw_resp)
                current_speed = 37
                if success and info.get("sig") == "PASS" and info.get("code") == 0 and len(data) > 2:
                    if data[0] & 0x80:
                        current_speed = data[0] - 128

                decel_steps = list(range(current_speed, 0, -5)) + [0]
                self.log_cleaner(f"Emergency decelerating in reverse: {decel_steps}...")
                for s in decel_steps:
                    payload = [0] * 128
                    payload[0] = s + 128
                    payload[1] = s + 128
                    payload[2] = (s + 128) if fan3_supported else 0
                    self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                    time.sleep(0.12)
            except Exception as e:
                self.log_cleaner(f"EMERGENCY STOP DECEL ERROR -> {e}")

        # Perform final stopping steps
        if mode == "legacy":
            try:
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and info["code"] == 0:
                    buf = data[:4]
                    buf[3] = (buf[3] | 0x02) & 0x7F
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
            except Exception as e:
                self.log_cleaner(f"LEGACY EMERGENCY STOP ERROR -> {e}")
        else: # modern
            try:
                payload = [0] * 128
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                time.sleep(2.0)
            except Exception as e:
                self.log_cleaner(f"MODERN EMERGENCY STOP ERROR -> {e}")

        self.config["mode"] = orig_mode
        self.save_config()
        self.apply_post_cleaner_mode()
        self.log_cleaner(f"EMERGENCY STOP COMPLETE -> Restored mode: '{orig_mode}'")
        return True, "Emergency stop completed. Fans restored to forwards mode."

    def apply_post_cleaner_mode(self):
        """Restores hardware fan mode smoothly after fan cleaning stops to prevent sudden 4.5k RPM spikes."""
        mode = self.config.get("mode", "auto")
        self.log_cleaner(f"APPLY POST CLEANER MODE -> Target mode: '{mode}'")
        try:
            # 1. Determine target PWM for smooth forward ramp-up
            if mode == "manual":
                target_pwm = self.config.get("manual_pwm", 128)
            elif mode == "curve":
                temp = self.get_reference_temp()
                target_pwm = self.calculate_target_pwm(temp) if temp else 128
            else:
                temp = self.get_reference_temp()
                target_pwm = self.calculate_target_pwm(temp) if temp else 120

            if target_pwm is None or target_pwm < 0:
                target_pwm = 120

            self.log_cleaner(f"FORWARD RAMP UP -> Ramping PWM from 30 up to {target_pwm}...")

            # 2. Smoothly ramp up forward PWM from 30 up to target_pwm in steps of 25
            if target_pwm > 40:
                for pwm_step in range(30, target_pwm, 25):
                    self.set_fan_pwm(pwm_step)
                    time.sleep(0.25)

            # 3. Hand control to final target mode
            if mode == "auto":
                self.set_fan_mode("auto")
                self.log_cleaner("RESTORED -> EC Automatic Fan Curve (pwm1_enable=2)")
            elif mode == "max":
                self.set_fan_mode("max")
                self.log_cleaner("RESTORED -> Max Speed Mode (pwm1_enable=0)")
            elif mode in ["manual", "curve"]:
                self.set_fan_pwm(target_pwm)
                self.log_cleaner(f"RESTORED -> {mode.capitalize()} Mode (pwm1_enable=1, PWM={target_pwm})")
            else:
                self.set_fan_mode("auto")
                self.log_cleaner("RESTORED -> Fallback EC Automatic (pwm1_enable=2)")
        except Exception as e:
            self.log_cleaner(f"ERROR in apply_post_cleaner_mode: {e}")
            try:
                self.set_fan_mode("auto")
            except Exception:
                pass

    def get_effective_fan_max(self):
        """Returns effective max fan RPM, using manual override/imported Windows config if set, otherwise calibrated fan_max."""
        if self.config.get("use_manual_max_rpm", False) or self.config.get("bypass_calibration", False):
            return int(self.config.get("manual_max_rpm", 5800))
        return int(self.config.get("fan_max", 0))

    def parse_omen_power_control_config(self, file_path):
        """
        Parses HP OMEN PowerControlConfig.json from file path or bytes.
        Handles Gzip decompression and UTF-16LE / UTF-8 decoding.
        Extracts CleanCreek fan parameters and Max Fan RPM upper bounds.
        """
        path = Path(file_path)
        if not path.exists():
            return False, f"File not found: {file_path}", {}

        try:
            with open(path, "rb") as f:
                raw_bytes = f.read()

            # 1. Check for Gzip magic bytes (\x1f\x8b\x08)
            gzip_idx = raw_bytes.find(b"\x1f\x8b\x08")
            if gzip_idx != -1:
                decomp = gzip.decompress(raw_bytes[gzip_idx:])
                try:
                    text = decomp.decode("utf-16le")
                except Exception:
                    text = decomp.decode("utf-8-sig", errors="ignore")
            else:
                try:
                    text = raw_bytes.decode("utf-16le")
                except Exception:
                    text = raw_bytes.decode("utf-8-sig", errors="ignore")

            data = json.loads(text)

            cpu_speed = data.get("CleanCreekCpuFanSpeed", 37)
            gpu_speed = data.get("CleanCreekGpuFanSpeed", 39)
            duration_ms = data.get("CleanCreekDuration", 30000)

            # Extract max fan speed / upper bound if available
            extracted_max_rpm = 5800 # Safe default
            try:
                fan_curve = data.get("SwFanControlCustomFanCurve", {})
                boundary = fan_curve.get("Boundary", {})
                upper_bounds = boundary.get("CPU_Fan_Speed_Upper_Bound_List", [])
                if upper_bounds and isinstance(upper_bounds, list):
                    max_idx = max(upper_bounds)
                    if max_idx > 0:
                        extracted_max_rpm = max_idx * 100
            except Exception as e:
                print(f"Could not extract fan curve upper bound: {e}")

            result = {
                "cleaner_cpu_speed": cpu_speed,
                "cleaner_gpu_speed": gpu_speed,
                "cleaner_duration_ms": duration_ms,
                "cleaner_duration_sec": int(duration_ms / 1000),
                "manual_max_rpm": extracted_max_rpm,
            }
            return True, "Successfully parsed PowerControlConfig.json", result
        except Exception as e:
            return False, f"Failed to parse PowerControlConfig.json: {e}", {}

    def import_windows_omen_config(self, target_path_or_dir):
        """
        Imports settings from a selected Windows mount point directory or PowerControlConfig.json file.
        Supports selecting drive root (/mnt/c), Users directory (/mnt/Users), user profile (/mnt/Users/Arda),
        AppData, HPOMEN folder, or PowerControlConfig.json directly.
        """
        try:
            target = Path(target_path_or_dir).expanduser().resolve()
        except Exception:
            target = Path(target_path_or_dir)

        actual_file = None

        if target.is_file():
            actual_file = target
        elif target.is_dir():
            rel_subpath = Path("AppData/Local/Packages/AD2F1837.OMENCommandCenter_v10z8vjag6ke6/LocalCache/Local/HPOMEN/PowerControlConfig.json")

            # 1. Selected "Users" directory directly (e.g. /mnt/Users or /media/drive/Users)
            if target.name.lower() in ["users", "user"]:
                try:
                    for user_folder in target.iterdir():
                        if user_folder.is_dir():
                            cand = user_folder / rel_subpath
                            if cand.exists():
                                actual_file = cand
                                break
                except Exception:
                    pass

            # 2. Selected drive root containing a "Users" folder (e.g. /mnt/c or /run/media/arda/ssd)
            if not actual_file:
                for u_name in ["Users", "users", "User", "user"]:
                    u_dir = target / u_name
                    if u_dir.exists() and u_dir.is_dir():
                        try:
                            for user_folder in u_dir.iterdir():
                                if user_folder.is_dir():
                                    cand = user_folder / rel_subpath
                                    if cand.exists():
                                        actual_file = cand
                                        break
                        except Exception:
                            pass
                    if actual_file:
                        break

            # 3. Selected user profile directory directly (e.g. /mnt/Users/Arda)
            if not actual_file:
                cand = target / rel_subpath
                if cand.exists():
                    actual_file = cand

            # 4. Selected AppData/Local folder
            if not actual_file:
                cand = target / "Packages/AD2F1837.OMENCommandCenter_v10z8vjag6ke6/LocalCache/Local/HPOMEN/PowerControlConfig.json"
                if cand.exists():
                    actual_file = cand

            # 5. Selected HPOMEN folder directly
            if not actual_file:
                cand = target / "PowerControlConfig.json"
                if cand.exists():
                    actual_file = cand

        if not actual_file or not actual_file.exists():
            return False, f"PowerControlConfig.json not found under selected location '{target_path_or_dir}'.", {}

        success, msg, parsed = self.parse_omen_power_control_config(actual_file)
        if not success:
            return False, msg, {}

        # Save extracted configuration parameters permanently
        self.config["cleaner_cpu_speed"] = parsed["cleaner_cpu_speed"]
        self.config["cleaner_gpu_speed"] = parsed["cleaner_gpu_speed"]
        self.config["cleaner_duration"] = parsed["cleaner_duration_sec"]
        self.config["windows_cleaner_duration"] = parsed["cleaner_duration_sec"]
        self.config["manual_max_rpm"] = parsed["manual_max_rpm"]
        self.config["windows_max_rpm"] = parsed["manual_max_rpm"]
        self.config["use_manual_max_rpm"] = True
        self.config["windows_config_imported"] = True
        self.save_config()

        return True, f"Imported configuration successfully from {actual_file.name}!", parsed

    def check_fan_cleaner_capability(self):
        """
        Queries WMI ACPI calls for CleanCreek fan cleaning hardware capability.
        Only returns True if /proc/acpi/call exists and BIOS responds with CleanCreek hardware support (e.g. OMEN MAX series).
        """
        if not Path("/proc/acpi/call").exists():
            return False

        try:
            caps = self.detect_cleaner_capabilities()
            if caps.get("modern", {}).get("supported", False) or caps.get("legacy", False):
                return True
        except Exception:
            pass

        return False

    def export_app_settings(self, file_path):
        """Exports current application configuration dictionary to a JSON file."""
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            return True, "Application settings exported successfully!"
        except Exception as e:
            return False, f"Failed to export settings: {e}"

    def import_app_settings(self, file_path):
        """Imports application settings with schema validation."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                imported_data = json.load(f)

            if not isinstance(imported_data, dict):
                return False, "Invalid settings file: Content is not a JSON object."

            # Check for required application keys
            expected_keys = {"mode", "curve", "cleaner_interval", "reference_sensor", "manual_max_rpm"}
            if not any(k in imported_data for k in expected_keys):
                return False, "Incompatible settings file: Required HP OMEN Fan Control keys not found."

            # Merge and save
            self.config.update(imported_data)
            self.save_config()
            return True, "Application settings imported successfully!"
        except Exception as e:
            return False, f"Failed to import settings: {e}"

