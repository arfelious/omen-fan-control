from __future__ import annotations

import os
from pathlib import Path


HWMON_PATH_PATTERN = "/sys/devices/platform/hp-wmi/hwmon/*/"
THERMAL_ZONE_PATH = "/sys/class/thermal/thermal_zone0/temp"
LOG_LEVELS: dict[str, int] = {
    "DEBUG": 0,
    "INFO": 1,
    "WARNING": 2,
    "ERROR": 3,
    "QUIET": 4,
}

if os.geteuid() == 0:
    CONFIG_DIR = Path("/etc/omen-fan-control")
else:
    CONFIG_DIR = Path(os.path.expanduser("~/.config/omen-fan-control"))

CONFIG_FILE = CONFIG_DIR / "config.json"
VOLATILE_CONFIG_DIR = Path("/run/omen-fan-control")
VOLATILE_CONFIG_FILE = VOLATILE_CONFIG_DIR / "config.json"

DEFAULT_CALIBRATION_WAIT = 30
DEFAULT_WATCHDOG_INTERVAL = 90
OMEN_FAN_DIR = Path(__file__).parent.absolute() / "data" / "driver" / "hp-wmi-omen"
CONFIG_VERSION = 1

SUPPORTED_BOARDS: set[str] = {
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
    "8C4D", "8C99", "8C9C", "8D26", "8D41", "8D87", "8A44", "8A4D", "8C58", "8BA9", "8BAA",
}

POSSIBLY_SUPPPORTED_OMEN_BOARDS: set[str] = {
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
    "8CF4", "8D2F",
}
