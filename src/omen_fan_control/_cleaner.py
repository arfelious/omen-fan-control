from __future__ import annotations

import json
import os
import struct
import threading
import time
import re
from pathlib import Path
from typing import TYPE_CHECKING

from ._constants import (
    CONFIG_DIR,
    LOG_LEVELS,
    VOLATILE_CONFIG_DIR,
)

if TYPE_CHECKING:
    from .fan_controller import FanController


class FanCleanerMixin:
    def log(self, message: str, level: str = "INFO") -> None:
        controller = self  # type: FanController
        target_level_name = str(controller.config.get("log_level", "INFO")).upper()
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

    def log_debug(self, msg: str) -> None:
        self.log("DEBUG", msg)

    def log_info(self, msg: str) -> None:
        self.log("INFO", msg)

    def log_warning(self, msg: str) -> None:
        self.log("WARNING", msg)

    def log_error(self, msg: str) -> None:
        self.log("ERROR", msg)

    def log_cleaner(self, message: str, level: str = "DEBUG") -> None:
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

    def get_cleaner_logs(self, max_lines: int = 60) -> str:
        for log_dir in [VOLATILE_CONFIG_DIR, CONFIG_DIR]:
            log_file = log_dir / "cleaner.log"
            if log_file.exists():
                try:
                    with open(log_file) as f:
                        lines = f.readlines()
                        return "".join(lines[-max_lines:])
                except Exception as e:
                    return f"Error reading logs: {e}"
        return "No cleaner logs found yet."

    def cleaner_acpi_call(self, method_id: int, command: int, command_type: int, data_size: int, payload_bytes: list[int]) -> str:
        controller = self  # type: FanController
        if not os.path.exists("/proc/acpi/call"):
            self.log_cleaner("ERROR: /proc/acpi/call does not exist! acpi_call module not loaded.")
            raise FileNotFoundError("acpi_call kernel module is not loaded (missing /proc/acpi/call).")

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
            with open("/proc/acpi/call") as f:
                response = f.read().strip()
            self.log_cleaner(f"ACPI RESP  -> {response[:100]}...")
            return response
        except PermissionError as pe:
            self.log_cleaner(f"PERMISSION ERROR -> Must run as root to write to /proc/acpi/call: {pe}")
            raise PermissionError("Must run as root to write to /proc/acpi/call.")
        except Exception as e:
            self.log_cleaner(f"ACPI ERROR -> {e}")
            raise

    def cleaner_parse_response(self, response: str) -> tuple[bool, str | dict | list, list]:
        if not response or response.startswith("Error"):
            self.log_cleaner(f"PARSE FAIL -> Response raw: {response}")
            return False, response, []

        clean_resp = response.replace("\x00", "").replace("{", "").replace("}", "").strip()
        if not clean_resp:
            self.log_cleaner("PARSE FAIL -> Empty response buffer")
            return False, "Empty response", []

        try:
            hex_tokens = re.findall(r'0x[0-9a-fA-F]+', clean_resp)
            if hex_tokens:
                byte_vals = [int(tok, 16) & 0xFF for tok in hex_tokens]
                resp_bytes = bytes(byte_vals)
            else:
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

    def detect_cleaner_capabilities(self) -> dict:
        modern_supported = False
        cpu_ok, gpu_ok, fan3_ok = False, False, False
        cpu_speed, gpu_speed, fan3_speed = 33, 0, 0
        try:
            raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
            success, info, data = self.cleaner_parse_response(raw_resp)
            if success and isinstance(info, dict) and info.get("sig") == "PASS" and info.get("code") == 0:
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
            if success and isinstance(info, dict) and info.get("code") == 0:
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
                "fan3_speed": fan3_speed,
            },
            "legacy": legacy_supported,
        }
        self.log_cleaner(f"CAPABILITIES RESULT -> {res}")
        return res

    def check_cleaner_auto_stop(self) -> bool:
        if self.config.get("cleaner_in_progress", False):
            start_ts = self.config.get("cleaner_start_time")
            if start_ts and (time.time() - start_ts >= 30):
                self.stop_fan_cleaning()
                return True
        return False

    def is_reverse_mode_active(self) -> bool:
        self.check_cleaner_auto_stop()

        if self.config.get("cleaner_in_progress", False):
            return True

        try:
            val1 = controller.read_sys_file(controller.fan1_input_path) if (controller := self) else None
            controller = self  # type: FanController
            val1 = controller.read_sys_file(controller.fan1_input_path)
            val2 = controller.read_sys_file(controller.fan2_input_path)
            if (val1 and int(val1) >= 12800) or (val2 and int(val2) >= 12800):
                return True
        except Exception:
            pass

        return False

    def start_fan_cleaning(self, speed: int | None = None) -> tuple[bool, str]:
        self.log_cleaner(f"START REQUESTED -> speed parameter: {speed}")

        controller = self  # type: FanController

        if controller.config.get("cleaner_in_progress", False) or controller.config.get("cleaner_transitioning", False):
            self.log_cleaner("START REJECTED -> Fan cleaning cycle is already in progress.")
            return False, "Fan cleaning cycle is already in progress."

        temp = controller.get_reference_temp()
        if temp is not None and temp > 70:
            self.log_cleaner(f"START ABORTED -> Temperature too high ({temp}°C > 70°C)")
            return False, f"Temperature too high ({temp}°C > 70°C). Cannot start fan cleaning."

        caps = self.detect_cleaner_capabilities()
        mode = "modern" if caps["modern"]["supported"] else ("legacy" if caps["legacy"] else "modern")
        self.log_cleaner(f"CHOSEN CLEANER MODE -> {mode.upper()}")

        orig_mode = controller.config.get("mode", "auto")
        orig_manual = controller.config.get("manual_pwm", -1)

        controller.config["cleaner_in_progress"] = False
        controller.config["cleaner_transitioning"] = True
        controller.config["cleaner_start_time"] = None
        controller.config["cleaner_orig_mode"] = orig_mode
        controller.config["cleaner_orig_manual"] = orig_manual
        controller.config["cleaner_mode"] = mode

        controller.save_config()
        controller.save_config(volatile=True)

        try:
            if mode == "legacy":
                self.log_cleaner("EXECUTING LEGACY START SEQUENCE...")
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and isinstance(info, dict) and info.get("code") == 0:
                    buf = data[:4]
                    buf[3] |= 0x82
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
                    controller.config["cleaner_in_progress"] = True
                    controller.config["cleaner_transitioning"] = False
                    controller.config["cleaner_start_time"] = time.time()
                    controller.save_config()
                    controller.save_config(volatile=True)
                    self.log_cleaner("LEGACY REVERSE MODE TRIGGERED SUCCESSFUL")
            else:
                cpu_speed_val = caps["modern"]["cpu_speed"] if caps["modern"]["cpu_speed"] > 0 else 33
                gpu_speed_val = caps["modern"]["gpu_speed"] if caps["modern"]["gpu_speed"] > 0 else 0
                fan3_speed_val = caps["modern"]["fan3_speed"] if caps["modern"]["fan3_speed"] > 0 else 0

                if speed is None:
                    if cpu_speed_val == 33 or cpu_speed_val == 0:
                        cpu_speed_val = 37
                    if gpu_speed_val == 0:
                        gpu_speed_val = 39
                else:
                    s_val = int(speed)
                    if s_val > 100:
                        s_val //= 100
                    s_val = min(max(s_val, 10), 39)
                    cpu_speed_val = s_val
                    gpu_speed_val = s_val
                    fan3_speed_val = s_val

                self.log_cleaner(f"EXECUTING MODERN REVERSE SEQUENCE -> Target Speeds: CPU={cpu_speed_val} ({cpu_speed_val*100} RPM), GPU={gpu_speed_val} ({gpu_speed_val*100} RPM)")

                payload = [0] * 128
                payload[0] = 128
                payload[1] = 128
                payload[2] = 128 if caps["modern"]["fan3"] else 0
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)

                start_wait = time.time()
                while time.time() - start_wait < 4.0:
                    val1 = controller.read_sys_file(controller.fan1_input_path)
                    val2 = controller.read_sys_file(controller.fan2_input_path)
                    rpm1, is_rev1 = controller.parse_hwmon_rpm(val1)
                    rpm2, is_rev2 = controller.parse_hwmon_rpm(val2)

                    tag1 = f"-{rpm1}" if is_rev1 else f"{rpm1}"
                    tag2 = f"-{rpm2}" if is_rev2 else f"{rpm2}"
                    self.log_cleaner(f"STEP 1 BRAKING -> fan1={tag1} RPM, fan2={tag2} RPM")
                    if rpm1 < 300 and rpm2 < 300:
                        self.log_cleaner(f"Braked to 0 RPM (fan1={tag1}, fan2={tag2}) in {time.time()-start_wait:.1f}s")
                        break
                    time.sleep(0.3)
                time.sleep(0.3)

                cpu_val = cpu_speed_val + 128
                gpu_val = gpu_speed_val + 128
                fan3_val = (fan3_speed_val + 128) if caps["modern"]["fan3"] else 0
                self.log_cleaner(f"STEP 2: Sending Reverse WMI payload -> CPU:{cpu_val} (0x{cpu_val:02X}), GPU:{gpu_val} (0x{gpu_val:02X}), Fan3:{fan3_val}")

                controller.config["cleaner_start_time"] = time.time()
                controller.config["cleaner_last_run"] = time.time()
                controller.config["cleaner_in_progress"] = True
                controller.config["cleaner_transitioning"] = False
                controller.save_config()
                controller.save_config(volatile=True)

                payload = [0] * 128
                payload[0] = cpu_val
                payload[1] = gpu_val
                payload[2] = fan3_val
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                parsed_ok, info, _ = self.cleaner_parse_response(raw_resp)
                if parsed_ok and isinstance(info, dict) and info.get("sig") == "FAIL":
                    self.log_cleaner(f"WARNING: WMI returned FAIL on reverse payload write (code: {info.get('code')})")

                time.sleep(0.5)

                rpm1, is_rev1 = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan1_input_path))
                rpm2, is_rev2 = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan2_input_path))
                is_rev = is_rev1 or is_rev2 or self.is_reverse_mode_active()
                self.log_cleaner(f"STEP 3: Hardware Reverse Check -> Active: {is_rev} (Fan1: {'-' if is_rev1 else ''}{rpm1} RPM, Fan2: {'-' if is_rev2 else ''}{rpm2} RPM)")

                cycle_id = time.time()
                controller.config["cleaner_cycle_id"] = cycle_id

                def _bg_auto_stop() -> None:
                    start_timer = time.time()
                    while time.time() - start_timer < 30:
                        time.sleep(3.0)
                        if not controller.config.get("cleaner_in_progress", False) or controller.config.get("cleaner_cycle_id") != cycle_id:
                            return
                        r1, rev1 = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan1_input_path))
                        r2, rev2 = controller.parse_hwmon_rpm(controller.read_sys_file(controller.fan2_input_path))
                        tag1 = f"-{r1}" if rev1 else f"{r1}"
                        tag2 = f"-{r2}" if rev2 else f"{r2}"
                        rem = max(0, int(30 - (time.time() - start_timer)))
                        self.log_cleaner(f"LIVE REVERSE STATUS ({rem}s remaining) -> Fan1: {tag1} RPM, Fan2: {tag2} RPM")

                    if controller.config.get("cleaner_in_progress", False) and controller.config.get("cleaner_cycle_id") == cycle_id:
                        self.log_cleaner("30-Second Auto-Stop Timer Fired -> Stopping cleaner...")
                        self.stop_fan_cleaning()

                threading.Thread(target=_bg_auto_stop, daemon=True).start()

            return True, "Fan cleaning started successfully."

        except Exception as e:
            self.log_cleaner(f"START SEQUENCE FAILED -> {e}. Rolling back to forwards mode!")
            self.emergency_stop_fan_cleaning()
            return False, f"Fan cleaning sequence failed: {e}"

    def stop_fan_cleaning(self) -> tuple[bool, str]:
        self.log_cleaner("STOP CLEANING REQUESTED")
        controller = self  # type: FanController

        mode = controller.config.get("cleaner_mode", "modern")
        orig_mode = controller.config.get("cleaner_orig_mode", "auto")

        controller.config["cleaner_in_progress"] = False
        controller.config["cleaner_transitioning"] = False
        controller.config["cleaner_last_run"] = time.time()
        controller.config.pop("cleaner_start_time", None)
        controller.config.pop("cleaner_cycle_id", None)
        controller.config.pop("cleaner_orig_mode", None)
        controller.config.pop("cleaner_orig_manual", None)
        controller.config.pop("cleaner_mode", None)
        controller.save_config()
        controller.save_config(volatile=True)

        if mode == "legacy":
            try:
                self.log_cleaner("EXECUTING LEGACY STOP SEQUENCE...")
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and isinstance(info, dict) and info.get("code") == 0:
                    buf = data[:4]
                    buf[3] = (buf[3] | 0x02) & 0x7F
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
            except Exception as e:
                self.log_cleaner(f"LEGACY STOP ERROR -> {e}")
        else:
            try:
                self.log_cleaner("EXECUTING MODERN STOP SEQUENCE...")
                caps = self.detect_cleaner_capabilities()
                fan3_supported = caps["modern"]["fan3"]
                current_speed = 37
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
                q_success, q_info, q_data = self.cleaner_parse_response(raw_resp)
                if q_success and isinstance(q_info, dict) and q_info.get("sig") == "PASS" and q_info.get("code") == 0 and len(q_data) > 2:
                    if q_data[0] & 0x80:
                        current_speed = q_data[0] - 128

                decel_steps = list(range(current_speed, 0, -5)) + [0]
                self.log_cleaner(f"Decelerating in reverse: {decel_steps}...")
                for s in decel_steps:
                    payload = [0] * 128
                    payload[0] = s + 128
                    payload[1] = s + 128
                    payload[2] = (s + 128) if fan3_supported else 0
                    self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                    time.sleep(0.15)

                self.log_cleaner("Releasing CleanCreek override [0, 0, 0]...")
                payload = [0] * 128
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                time.sleep(2.0)
            except Exception as e:
                self.log_cleaner(f"MODERN STOP ERROR -> {e}")

        controller.config["mode"] = orig_mode
        controller.save_config()
        self.apply_post_cleaner_mode()
        self.log_cleaner(f"CLEANER STOP COMPLETE -> Restored mode: '{orig_mode}'")
        return True, "Fan cleaning stopped."

    def emergency_stop_fan_cleaning(self) -> tuple[bool, str]:
        self.log_cleaner("EMERGENCY STOP REQUESTED!")
        controller = self  # type: FanController

        mode = controller.config.get("cleaner_mode", "modern")
        orig_mode = controller.config.get("cleaner_orig_mode", controller.config.get("mode", "auto"))

        controller.config["cleaner_in_progress"] = False
        controller.config["cleaner_transitioning"] = False
        controller.config.pop("cleaner_start_time", None)
        controller.config.pop("cleaner_cycle_id", None)
        controller.config.pop("cleaner_orig_mode", None)
        controller.config.pop("cleaner_orig_manual", None)
        controller.config.pop("cleaner_mode", None)
        controller.save_config()
        controller.save_config(volatile=True)

        if mode == "modern" and os.path.exists("/proc/acpi/call"):
            try:
                caps = self.detect_cleaner_capabilities()
                fan3_supported = caps["modern"]["fan3"]
                raw_resp = self.cleaner_acpi_call(method_id=3, command=131080, command_type=44, data_size=128, payload_bytes=[0]*128)
                success, info, data = self.cleaner_parse_response(raw_resp)
                current_speed = 37
                if success and isinstance(info, dict) and info.get("sig") == "PASS" and info.get("code") == 0 and len(data) > 2:
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

        if mode == "legacy":
            try:
                raw_resp = self.cleaner_acpi_call(method_id=2, command=1, command_type=44, data_size=4, payload_bytes=[0]*4)
                success, info, data = self.cleaner_parse_response(raw_resp)
                if success and isinstance(info, dict) and info.get("code") == 0:
                    buf = data[:4]
                    buf[3] = (buf[3] | 0x02) & 0x7F
                    self.cleaner_acpi_call(method_id=2, command=2, command_type=44, data_size=4, payload_bytes=buf)
            except Exception as e:
                self.log_cleaner(f"LEGACY EMERGENCY STOP ERROR -> {e}")
        else:
            try:
                payload = [0] * 128
                self.cleaner_acpi_call(method_id=3, command=131080, command_type=46, data_size=128, payload_bytes=payload)
                time.sleep(2.0)
            except Exception as e:
                self.log_cleaner(f"MODERN EMERGENCY STOP ERROR -> {e}")

        controller.config["mode"] = orig_mode
        controller.save_config()
        self.apply_post_cleaner_mode()
        self.log_cleaner(f"EMERGENCY STOP COMPLETE -> Restored mode: '{orig_mode}'")
        return True, "Emergency stop completed. Fans restored to forwards mode."

    def apply_post_cleaner_mode(self) -> None:
        controller = self  # type: FanController
        mode = controller.config.get("mode", "auto")
        self.log_cleaner(f"APPLY POST CLEANER MODE -> Target mode: '{mode}'")
        try:
            if mode == "manual":
                target_pwm = controller.config.get("manual_pwm", 128)
            elif mode == "curve":
                temp = controller.get_reference_temp()
                target_pwm = controller.calculate_target_pwm(temp) if temp else 128
            else:
                temp = controller.get_reference_temp()
                target_pwm = controller.calculate_target_pwm(temp) if temp else 120

            if target_pwm is None or target_pwm < 0:
                target_pwm = 120

            self.log_cleaner(f"FORWARD RAMP UP -> Ramping PWM from 30 up to {target_pwm}...")

            if target_pwm > 40:
                for pwm_step in range(30, target_pwm, 25):
                    controller.set_fan_pwm(pwm_step)
                    time.sleep(0.25)

            if mode == "auto":
                controller.set_fan_mode("auto")
                self.log_cleaner("RESTORED -> EC Automatic Fan Curve (pwm1_enable=2)")
            elif mode == "max":
                controller.set_fan_mode("max")
                self.log_cleaner("RESTORED -> Max Speed Mode (pwm1_enable=0)")
            elif mode in ["manual", "curve"]:
                controller.set_fan_pwm(target_pwm)
                self.log_cleaner(f"RESTORED -> {mode.capitalize()} Mode (pwm1_enable=1, PWM={target_pwm})")
            else:
                controller.set_fan_mode("auto")
                self.log_cleaner("RESTORED -> Fallback EC Automatic (pwm1_enable=2)")
        except Exception as e:
            self.log_cleaner(f"ERROR in apply_post_cleaner_mode: {e}")
            try:
                controller.set_fan_mode("auto")
            except Exception:
                pass

    def check_fan_cleaner_capability(self) -> bool:
        if not Path("/proc/acpi/call").exists():
            return False

        try:
            caps = self.detect_cleaner_capabilities()
            if caps.get("modern", {}).get("supported", False) or caps.get("legacy", False):
                return True
        except Exception:
            pass

        return False

    def parse_omen_power_control_config(self, file_path: str) -> tuple[bool, str, dict]:
        path = Path(file_path)
        if not path.exists():
            return False, f"File not found: {file_path}", {}

        try:
            with open(path, "rb") as f:
                raw_bytes = f.read()

            gzip_idx = raw_bytes.find(b"\x1f\x8b\x08")
            if gzip_idx != -1:
                import gzip
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

            extracted_max_rpm = 5800
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

    def import_windows_omen_config(self, target_path_or_dir: str) -> tuple[bool, str, dict]:
        controller = self  # type: FanController
        try:
            target = Path(target_path_or_dir).expanduser().resolve()
        except Exception:
            target = Path(target_path_or_dir)

        actual_file = None

        if target.is_file():
            actual_file = target
        elif target.is_dir():
            rel_subpath = Path("AppData/Local/Packages/AD2F1837.OMENCommandCenter_v10z8vjag6ke6/LocalCache/Local/HPOMEN/PowerControlConfig.json")

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

            if not actual_file:
                cand = target / rel_subpath
                if cand.exists():
                    actual_file = cand

            if not actual_file:
                cand = target / "Packages/AD2F1837.OMENCommandCenter_v10z8vjag6ke6/LocalCache/Local/HPOMEN/PowerControlConfig.json"
                if cand.exists():
                    actual_file = cand

            if not actual_file:
                cand = target / "PowerControlConfig.json"
                if cand.exists():
                    actual_file = cand

        if not actual_file or not actual_file.exists():
            return False, f"PowerControlConfig.json not found under selected location '{target_path_or_dir}'.", {}

        success, msg, parsed = self.parse_omen_power_control_config(str(actual_file))
        if not success:
            return False, msg, {}

        controller.config["cleaner_cpu_speed"] = parsed["cleaner_cpu_speed"]
        controller.config["cleaner_gpu_speed"] = parsed["cleaner_gpu_speed"]
        controller.config["cleaner_duration"] = parsed["cleaner_duration_sec"]
        controller.config["windows_cleaner_duration"] = parsed["cleaner_duration_sec"]
        controller.config["manual_max_rpm"] = parsed["manual_max_rpm"]
        controller.config["windows_max_rpm"] = parsed["manual_max_rpm"]
        controller.config["use_manual_max_rpm"] = True
        controller.config["windows_config_imported"] = True
        controller.save_config()

        return True, f"Imported configuration successfully from {actual_file.name}!", parsed

    def export_app_settings(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, indent=2)
            return True, "Application settings exported successfully!"
        except Exception as e:
            return False, f"Failed to export settings: {e}"

    def import_app_settings(self, file_path: str) -> tuple[bool, str]:
        try:
            with open(file_path, encoding="utf-8") as f:
                imported_data = json.load(f)

            if not isinstance(imported_data, dict):
                return False, "Invalid settings file: Content is not a JSON object."

            expected_keys = {"mode", "curve", "cleaner_interval", "reference_sensor", "manual_max_rpm"}
            if not any(k in imported_data for k in expected_keys):
                return False, "Incompatible settings file: Required HP OMEN Fan Control keys not found."

            self.config.update(imported_data)
            self.save_config()
            return True, "Application settings imported successfully!"
        except Exception as e:
            return False, f"Failed to import settings: {e}"
