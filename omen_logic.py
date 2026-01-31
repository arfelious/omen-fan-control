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
import json
import time
import math
import shutil
import subprocess
from pathlib import Path

# Constants
HWMON_PATH_PATTERN = "/sys/devices/platform/hp-wmi/hwmon/*/"
THERMAL_ZONE_PATH = "/sys/class/thermal/thermal_zone0/temp"
CONFIG_DIR = Path("/etc/omen-fan-control")
CONFIG_FILE = CONFIG_DIR / "config.json"
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
    "8A15", "8A42", "8BAD",
    
    "8A25",
    "8BBE", "8BD4", "8BD5", "8C78", "8C99", "8C9C", "8D41"
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
        """
        Checks if the current board is in the supported list.
        Returns (is_supported, board_name)
        """
        try:
            with open("/sys/class/dmi/id/board_name", "r") as f:
                board_name = f.read().strip()
            
            return board_name in SUPPORTED_BOARDS, board_name
        except Exception as e:
            print(f"Error reading board name: {e}")
            return False, "Unknown"

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
        """Loads configuration from JSON file."""
        defaults = {
            "version": CONFIG_VERSION,
            "fan_max": 0,
            "calibration_wait": DEFAULT_CALIBRATION_WAIT,
            "watchdog_interval": DEFAULT_WATCHDOG_INTERVAL,
            "ma_window": 5,
            "curve": [],
            "bypass_warning": False,
            "mode": "auto",
            "manual_pwm": 0,
            "curve_interpolation": "smooth"
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
        """Saves current configuration to JSON file."""
        if self.config_path.parent:
             self.config_path.parent.mkdir(parents=True, exist_ok=True)
        
        self.config["version"] = CONFIG_VERSION
        with open(self.config_path, "w") as f:
            json.dump(self.config, f, indent=4)

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

    def get_fan_speed(self):
        """Returns current fan speed in RPM."""
        val = self.read_sys_file(self.fan1_input_path)
        return int(val) if val else 0

    def get_cpu_temp(self):
        """Returns CPU temp in Celsius."""
        if self.cpu_temp_path:
            val = self.read_sys_file(self.cpu_temp_path)
            return int(val) // 1000 if val else 0
        return 0


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
        """Patches hp-wmi.c with the max rpm value."""
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

        # Replace define
        max_rpm_val = math.floor(fan_max / 100)
        new_define = f"#define OMEN_MAX_RPM {max_rpm_val}"
        
        new_content = content.replace("#define OMEN_MAX_RPM 60", new_define)
        
        with open(target_file, "w") as f:
            f.write(new_content)
            
        return True, "Patch applied successfully."

    def install_driver_temp(self, force=False):
        """Installs driver temporarily using insmod. Requires calibration first."""
        if self.pwm1_path and self.pwm1_path.exists():
            bypass = self.config.get("bypass_patch_warning", False)
            if not force and not bypass:
                return False, "PWM_DETECTED"

        fan_max = self.config.get("fan_max", 0)
        if fan_max == 0:
            return False, "Error: Please calibrate first to get Max RPM."

        success, msg = self._patch_driver_source(fan_max)
        if not success:
             return False, msg

        try:
            subprocess.run(["make"], check=True, cwd=OMEN_FAN_DIR, capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, f"Make failed: {e.stderr}"
        
        ko_files = list(OMEN_FAN_DIR.glob("*.ko"))
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
        
        subprocess.run(["make", "clean"], check=True, cwd=OMEN_FAN_DIR)
        
        self.config["install_type"] = "temporary"
        self.save_config()
             
        return True, "Temporary driver installed successfully."

    def install_driver_perm(self, force=False):
        """Installs driver permanently by patching and running install script."""
        if self.pwm1_path and self.pwm1_path.exists():
            bypass = self.config.get("bypass_patch_warning", False)
            if not force and not bypass:
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
        """Determines installation type: 'permanent', 'temporary', or None."""
        if not (self.pwm1_path and self.pwm1_path.exists()):
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
                
            subprocess.run(["sudo", "mv", "omen-fan-control.service", str(service_path)], check=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            subprocess.run(["sudo", "systemctl", "enable", "omen-fan-control.service"], check=True)
            subprocess.run(["sudo", "systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service created and started."
        except Exception as e:
            return False, f"Failed to create service: {e}"

    def remove_service(self):
        """Stops and removes the systemd service."""
        try:
            subprocess.run(["sudo", "systemctl", "stop", "omen-fan-control.service"], check=False)
            subprocess.run(["sudo", "systemctl", "disable", "omen-fan-control.service"], check=False)
            
            service_path = Path("/etc/systemd/system/omen-fan-control.service")
            if service_path.exists():
                subprocess.run(["sudo", "rm", str(service_path)], check=True)
                
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
            return True, "Service removed."
        except Exception as e:
            return False, f"Failed to remove service: {e}"

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
                    subprocess.run(["sudo", "dkms", "remove", f"{dkms_name}/{dkms_version}", "--all"], check=False)
                    messages.append("Removed DKMS module.")
            except FileNotFoundError:
                pass  # DKMS not installed
            
            # 2. Remove DKMS source directory
            dkms_src = Path(f"/usr/src/{dkms_name}-{dkms_version}")
            if dkms_src.exists():
                subprocess.run(["sudo", "rm", "-rf", str(dkms_src)], check=False)
            
            # 3. Remove our kernel hooks source
            hook_src = Path(f"/usr/src/{dkms_name}")
            if hook_src.exists():
                subprocess.run(["sudo", "rm", "-rf", str(hook_src)], check=False)
            
            # 4. Remove distro-specific kernel hooks
            hook_paths = [
                "/etc/pacman.d/hooks/90-hp-wmi-omen.hook",  # Arch
                "/etc/kernel/postinst.d/zz-hp-wmi-omen",   # Debian/Ubuntu
                "/etc/kernel/install.d/99-hp-wmi-omen.install",  # Fedora
            ]
            for hook in hook_paths:
                if Path(hook).exists():
                    subprocess.run(["sudo", "rm", hook], check=False)
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
                        subprocess.run(["sudo", "mv", str(bak_file), str(target)], check=True)
                        restored_count += 1
            
            if restored_count == 0 and not messages:
                if self.config.get("install_type") == "temporary":
                     subprocess.run(["sudo", "modprobe", "-r", "hp-wmi"], check=False)
                     subprocess.run(["sudo", "modprobe", "hp-wmi"], check=False)
                     self.config.pop("install_type", None)
                     self.save_config()
                     return True, "Temporary driver unloaded. (No backups needed)"
                
                return False, "No backup files (.bak) found to restore."

            subprocess.run(["sudo", "depmod", "-a"], check=True)
            subprocess.run(["sudo", "modprobe", "-r", "hp-wmi"], check=False) 
            subprocess.run(["sudo", "modprobe", "hp-wmi"], check=True)
            
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

