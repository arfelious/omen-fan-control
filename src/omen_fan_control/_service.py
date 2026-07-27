from __future__ import annotations

import json
import sys
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from ._constants import OMEN_FAN_DIR, VOLATILE_CONFIG_FILE

if TYPE_CHECKING:
    pass


class ServiceManagerMixin:
    def create_service(self) -> tuple[bool, str]:
        service_content = f"""[Unit]
Description=HP Omen Fan Control Service
After=multi-user.target

[Service]
Type=simple
        ExecStart={sys.executable} -m omen_fan_control.cli serve
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
            service_path.parent.mkdir(parents=True, exist_ok=True)
            service_path.write_text(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "omen-fan-control.service"], check=True)
            subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service created and started."
        except Exception as e:
            return False, f"Failed to create service: {e}"

    def remove_service(self) -> tuple[bool, str]:
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

    def restart_service(self) -> tuple[bool, str]:
        try:
            subprocess.run(["systemctl", "restart", "omen-fan-control.service"], check=True)
            return True, "Service restarted."
        except Exception as e:
            return False, f"Failed to restart service: {e}"

    def start_service(self) -> tuple[bool, str]:
        try:
            subprocess.run(["systemctl", "start", "omen-fan-control.service"], check=True)
            return True, "Service started."
        except Exception as e:
            return False, f"Failed to start service: {e}"

    def stop_service(self) -> tuple[bool, str]:
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-control.service"], check=True)
            return True, "Service stopped."
        except Exception as e:
            return False, f"Failed to stop service: {e}"

    @staticmethod
    def is_service_installed() -> bool:
        return Path("/etc/systemd/system/omen-fan-control.service").exists()

    @staticmethod
    def is_service_running() -> bool:
        try:
            res = subprocess.run(["systemctl", "is-active", "omen-fan-control.service"], capture_output=True, text=True)
            return res.stdout.strip() == "active"
        except Exception:
            return False

    def create_shutdown_service(self) -> tuple[bool, str]:
        service_content = f"""[Unit]
Description=HP Omen Fan Control Shutdown Hook
DefaultDependencies=no
Before=shutdown.target reboot.target halt.target

[Service]
Type=oneshot
ExecStart=/usr/bin/true
ExecStop={sys.executable} -m omen_fan_control.cli fan-control --mode manual --value 30% --no-save --source shutdown-hook
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
"""
        service_path = Path("/etc/systemd/system/omen-fan-shutdown.service")

        try:
            service_path.parent.mkdir(parents=True, exist_ok=True)
            service_path.write_text(service_content)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", "omen-fan-shutdown.service"], check=True)
            subprocess.run(["systemctl", "start", "omen-fan-shutdown.service"], check=True)

            self.config["shutdown_hook_enabled"] = True
            self.save_config()

            return True, f"Shutdown hook service created at {service_path} and enabled."
        except Exception as e:
            return False, f"Failed to create shutdown hook: {e}"

    def remove_shutdown_service(self) -> tuple[bool, str]:
        try:
            subprocess.run(["systemctl", "stop", "omen-fan-shutdown.service"], check=False)
            subprocess.run(["systemctl", "disable", "omen-fan-shutdown.service"], check=False)

            service_path = Path("/etc/systemd/system/omen-fan-shutdown.service")
            if service_path.exists():
                subprocess.run(["rm", str(service_path)], check=True)

            subprocess.run(["systemctl", "daemon-reload"], check=True)

            if VOLATILE_CONFIG_FILE.exists():
                try:
                    with open(VOLATILE_CONFIG_FILE) as f:
                        v_data = json.load(f)
                    if v_data.get("config_source") == "shutdown-hook":
                        VOLATILE_CONFIG_FILE.unlink()
                        print(f"Cleaned up shutdown-hook config at {VOLATILE_CONFIG_FILE}")
                except Exception:
                    pass

            self.config["shutdown_hook_enabled"] = False
            self.save_config()

            return True, f"Shutdown hook service removed from {service_path}."
        except Exception as e:
            return False, f"Failed to remove shutdown hook: {e}"

    @staticmethod
    def is_shutdown_service_enabled() -> bool:
        return Path("/etc/systemd/system/omen-fan-shutdown.service").exists()
