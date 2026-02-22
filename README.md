# HP Omen Fan Control (Linux)

This tool provides fan control for HP Omen Max, Victus and Omen laptops on Linux. It includes installer for a kernel driver patch (`hp-wmi`) to expose PWM controls and a userspace utility to manage fan curves, create watchdog that sets the fan configuration periodically and a simple stress test tool to see the fan curve in effect.

## Context

This tool includes a backported `hp-wmi` driver patch from the upcoming Linux 6.20 kernel, which introduces native fan control support for many devices from the following models:

1. **HP Omen Max**
2. **HP Victus**
3. **HP Omen**

The patch can be installed on versions before `6.20`.

**Reference Kernel Commit:**
[platform/x86: hp-wmi: add manual fan control for Victus S models](https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c)

This program also includes a modification that sets the max speed according to calibration if the query to get the Max RPM fails for your device.

## Tested Hardware

- **Model:** HP OMEN MAX 16-AH0001NT (8D41)
- **OS:** Arch Linux 6.18.6

## Installation

Choose one of the following: **pipx/uv** (recommended), **Arch Linux packages**, or **clone + run from source**.

### Option A: pipx or uv (recommended)

Install the app in an isolated environment. Driver sources are bundled; you can run `install-patch` from the app.

**Using pipx:**

```bash
pipx install git+https://github.com/arfelious/omen-fan-control.git
# Then:
sudo omen-fan-control status
sudo omen-fan-control-gui   # GUI
```

**Using uv:**

```bash
uv tool install git+https://github.com/arfelious/omen-fan-control.git
sudo omen-fan-control status
sudo omen-fan-control-gui
```

**System deps (for driver build):** install kernel headers and build tools (e.g. Arch: `linux-headers base-devel`, Debian/Ubuntu: `linux-headers-$(uname -r) build-essential`).

### Option B: Arch Linux (PKGBUILD)

Two packages: the **DKMS kernel module** (optional; persists across kernel updates) and the **Python app**.

1. **Kernel module (DKMS)** – run from the package dir (makepkg needs PKGBUILD in cwd):
  ```bash
  cd omen-fan-control/arch/hp-wmi-omen && makepkg -sf
  sudo pacman -U hp-wmi-omen-dkms-*.pkg.tar.zst
  ```
2. **Python application** – run from the package dir:
  ```bash
  cd omen-fan-control/arch/omen-fan-control && makepkg -sf
  sudo pacman -U omen-fan-control-*.pkg.tar.zst
  ```
   Driver data is installed under `/usr/share/omen-fan-control`; the app uses it when you run `install-patch permanent` (e.g. for calibration-based patching). Set `OMEN_FAN_CONTROL_DIR=/usr/share/omen-fan-control` if not using the provided `profile.d` snippet.

### Option C: Clone and run from source (single copy under `src/`)

All code and driver sources live under `src/`

```bash
git clone https://github.com/arfelious/omen-fan-control.git
cd omen-fan-control
```

**Dependencies**

- **System:** kernel headers and build tools (Arch: `pacman -S linux-headers base-devel`; Debian/Ubuntu: `apt install linux-headers-$(uname -r) build-essential`).
- **Python:** `click`, `PyQt6`. Either use **uv** (recommended) or pip.

**Run from repo (no install)**

With **uv** (adds project to path automatically):

```bash
uv sync
uv run omen-fan-control --help
uv run omen-fan-control-gui
sudo uv run omen-fan-control install-patch permanent
sudo uv run omen-fan-control service install
```

With **pip** (run the package module with `src` on `PYTHONPATH`):

```bash
pip install -r requirements.txt
export PYTHONPATH=src
python -m omen_fan_control.cli --help
python -m omen_fan_control.gui
sudo env PYTHONPATH=src python -m omen_fan_control.cli install-patch permanent
sudo env PYTHONPATH=src python -m omen_fan_control.cli service install
```

Or install the package in editable mode and use the same commands as pipx:

```bash
uv sync   # or: pip install -e .
uv run omen-fan-control status
sudo uv run omen-fan-control-gui
```

## Usage

- **Installed** (pipx, uv tool, or Arch): run `omen-fan-control` and `omen-fan-control-gui`.
- **From clone:** run `uv run omen-fan-control` / `uv run omen-fan-control-gui`, or `PYTHONPATH=src python -m omen_fan_control.cli` / `python -m omen_fan_control.gui`.

Examples below use `omen-fan-control`; from clone use one of the forms above.

### GUI

```bash
sudo omen-fan-control-gui
```

**GUI Fan Curve**

|<img width="400" height="300" alt="Omen Fan Control GUI" src="https://github.com/user-attachments/assets/57f1a966-d7a6-4c5f-8090-a1e947349bd9" />|
|---|


### CLI

**Check status**

```bash
sudo omen-fan-control status
```

**Settings**

```bash
omen-fan-control settings --help
omen-fan-control settings
sudo omen-fan-control options --ma-window 10 --curve-interpolation smooth
```

**Fan control**

```bash
# Manual speed
sudo omen-fan-control fan-control --mode manual --value 80%

# Curve mode (requires service)
sudo omen-fan-control fan-control --mode curve

# Auto (default)
sudo omen-fan-control fan-control --mode auto

# Custom curve CSV (temp, percent per line)
sudo omen-fan-control fan-control --curve-csv my_curve.csv
```

**Other**

```bash
omen-fan-control fan-control --help
```

## Uninstallation

1. **Remove service**
  ```bash
   sudo omen-fan-control service remove
  ```
2. **Restore original driver**
  ```bash
   sudo omen-fan-control install-patch restore
  ```
   Restores the original `.ko` files from backups created during installation.

## Disclaimer

**USE AT YOUR OWN RISK.**
Modifying kernel drivers and manipulating thermal control systems can potentially damage your hardware or cause instability. This software is provided "as is" without warranty of any kind. This was tested on my personal hardware, and the used `hp-wmi.c` is a patched version of the one in the upcoming `6.20` kernel, so your mileage may vary.

Acknowledgements  


**Probes:**

- [https://github.com/alou-S/omen-fan/blob/main/docs/probes.md](https://github.com/alou-S/omen-fan/blob/main/docs/probes.md)

**Linux 6.20 Kernel HP-WMI Driver:**

- [https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c](https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c)

