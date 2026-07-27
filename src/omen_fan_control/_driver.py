from __future__ import annotations

import math
import shutil
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ._constants import OMEN_FAN_DIR

if TYPE_CHECKING:
    from .fan_controller import FanController


class DriverInstallerMixin:
    def _patch_driver_source(self, fan_max: int) -> tuple[bool, str]:
        orig_file = OMEN_FAN_DIR / "hp-wmi-omen" / "hp-wmi.c.orig"
        target_file = OMEN_FAN_DIR / "hp-wmi-omen" / "hp-wmi.c"

        if not orig_file.exists():
            if target_file.exists():
                shutil.copy(target_file, orig_file)
            else:
                return False, "Error: hp-wmi.c not found."

        with open(orig_file) as f:
            content = f.read()

        max_rpm_val = math.floor(fan_max / 100)
        new_define = f"#define OMEN_MAX_RPM {max_rpm_val}"
        content = content.replace("#define OMEN_MAX_RPM 60", new_define)

        if self.config.get("enable_experimental", False):
            board_name = self.config.get("cached_board_name")
            if not board_name:
                _, board_name = self.check_board_support()

            if board_name and board_name != "Unknown":
                profile = self.config.get("thermal_profile", "omen")

                target_array = "omen_thermal_profile_boards"
                params_struct = "victus_s_thermal_params"

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
                    end_idx = content.find("};", start_idx)
                    if end_idx != -1:
                        segment = content[start_idx:end_idx]
                        if f'"{board_name}"' not in segment:
                            if target_array == "victus_s_thermal_profile_boards":
                                sentinel_idx = content.find("{},", start_idx)
                                if sentinel_idx == -1 or sentinel_idx > end_idx:
                                    sentinel_idx = content.find("{}", start_idx)

                                if sentinel_idx != -1 and sentinel_idx < end_idx:
                                    insertion = (
                                        f'        {{\n'
                                        f'            .matches = {{DMI_MATCH(DMI_BOARD_NAME, "{board_name}")}},\n'
                                        f'            .driver_data = (void *)&{params_struct},\n'
                                        f'        }},\n'
                                    )
                                    content = content[:sentinel_idx] + insertion + content[sentinel_idx:]
                                else:
                                    insertion = (
                                        f'        {{\n'
                                        f'            .matches = {{DMI_MATCH(DMI_BOARD_NAME, "{board_name}")}},\n'
                                        f'            .driver_data = (void *)&{params_struct},\n'
                                        f'        }},\n'
                                    )
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

    def install_driver_temp(self, force: bool = False) -> tuple[bool, str]:
        controller = self  # type: FanController
        if controller.pwm1_path and controller.pwm1_path.exists():
            bypass = controller.config.get("bypass_patch_warning", False)
            if not force and not bypass:
                return False, "PWM_DETECTED"

        fan_max = controller.get_effective_fan_max()
        if fan_max == 0:
            return False, "Error: Please calibrate or set Manual Max RPM in Options."

        success, msg = self._patch_driver_source(fan_max)
        if not success:
            return False, msg

        try:
            subprocess.run(["make"], check=True, cwd=OMEN_FAN_DIR / "hp-wmi-omen", capture_output=True, text=True)
        except subprocess.CalledProcessError as e:
            return False, self._format_make_error(e.stderr)

        ko_files = list((OMEN_FAN_DIR / "hp-wmi-omen").glob("*.ko"))
        if not ko_files:
            return False, "Error: No .ko file found after make."

        subprocess.run(["modprobe", "-r", "hp-wmi"], check=False)

        try:
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

        subprocess.run(["make", "clean"], cwd=OMEN_FAN_DIR / "hp-wmi-omen", check=False, capture_output=True)

        controller.config["install_type"] = "temporary"
        controller.save_config()

        return True, "Temporary driver installed successfully."

    def install_driver_perm(self, force: bool = False) -> tuple[bool, str]:
        controller = self  # type: FanController
        if controller.pwm1_path and controller.pwm1_path.exists():
            bypass = controller.config.get("bypass_patch_warning", False)
            if not force and not bypass:
                return False, "PWM_DETECTED"

        fan_max = controller.get_effective_fan_max()
        if fan_max == 0:
            return False, "Error: Please calibrate or set Manual Max RPM in Options."

        success, msg = self._patch_driver_source(fan_max)
        if not success:
            return False, msg

        try:
            subprocess.run(["/bin/bash", "install_driver.sh"], cwd=OMEN_FAN_DIR, check=True)
        except subprocess.CalledProcessError:
            return False, "Install script failed. Check terminal output above for details."

        controller.config["install_type"] = "permanent"
        controller.save_config()

        return True, "Permanent driver installed successfully."

    def check_install_type(self) -> str | None:
        controller = self  # type: FanController
        if not (controller.pwm1_enable_path and controller.pwm1_enable_path.exists()):
            return None

        conf_type = controller.config.get("install_type")
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

    def get_effective_fan_max(self) -> int:
        if self.config.get("use_manual_max_rpm", False) or self.config.get("bypass_calibration", False):
            return int(self.config.get("manual_max_rpm", 5800))
        return int(self.config.get("fan_max", 0))

    def restore_driver(self) -> tuple[bool, str]:
        messages: list[str] = []

        try:
            dkms_name = "hp-wmi-omen"
            dkms_version = "1.0"
            try:
                result = subprocess.run(["dkms", "status"], capture_output=True, text=True)
                if dkms_name in result.stdout:
                    subprocess.run(["dkms", "remove", f"{dkms_name}/{dkms_version}", "--all"], check=False)
                    messages.append("Removed DKMS module.")
            except FileNotFoundError:
                pass

            dkms_src = Path(f"/usr/src/{dkms_name}-{dkms_version}")
            if dkms_src.exists() and dkms_name in str(dkms_src) and len(str(dkms_src)) > 10:
                subprocess.run(["rm", "-rf", str(dkms_src)], check=False)

            hook_src = Path(f"/usr/src/{dkms_name}")
            if hook_src.exists() and dkms_name in str(hook_src) and len(str(hook_src)) > 10:
                subprocess.run(["rm", "-rf", str(hook_src)], check=False)

            hook_paths = [
                "/etc/pacman.d/hooks/90-hp-wmi-omen.hook",
                "/etc/kernel/postinst.d/zz-hp-wmi-omen",
                "/etc/kernel/install.d/99-hp-wmi-omen.install",
            ]
            for hook in hook_paths:
                if Path(hook).exists():
                    subprocess.run(["rm", hook], check=False)
                    messages.append(f"Removed hook: {Path(hook).name}")

            kernel_ver = subprocess.check_output(["uname", "-r"]).decode().strip()
            search_paths = [
                Path(f"/lib/modules/{kernel_ver}/kernel/drivers/platform/x86/hp"),
                Path(f"/lib/modules/{kernel_ver}/updates"),
            ]

            restored_count = 0

            for search_dir in search_paths:
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

            return True, " ".join(messages)

        except subprocess.CalledProcessError as e:
            return False, f"Error restoring driver: {e}"
        except Exception as e:
            return False, f"Error: {e}"
