# HP Omen Fan Control (Linux)

This tool provides fan control for HP Omen Max, Victus and Omen laptops on Linux. It includes installer for a kernel driver patch (`hp-wmi`) to expose PWM controls and a userspace utility to manage fan curves, create watchdog that sets the fan configuration periodically and a simple stress test tool to see the fan curve in effect. It also allows periodically reversing the fan spin direction on supported boards to expel dust.

## Context

This tool includes a backported `hp-wmi` driver patch from the latest Linux kernel, which introduces native fan control support for many devices from the following models:

1. **HP Omen Max**
2. **HP Victus**
3. **HP Omen**

The patch can be installed on versions before `6.20` as well.

**Reference Kernel Commit:**
[platform/x86: hp-wmi: add manual fan control for Victus S models](https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c)

This program also includes a modification that sets the max speed according to calibration if the query to get the Max RPM fails for your device.

## Tested Hardware
* **Models:** HP OMEN MAX 16-AH0xxxNT (8D41), HP OMEN Transcend 16-u1xxx (8C4D), HP OMEN Transcend 16-u0xxx (8BB3), OMEN by HP Gaming Laptop 16-xf0xxx (8BCA), HP Victus 16 s1xxx (8C9C), HP Omen 15 ek1xxx (88C8)

* **OS:** Arch Linux 6.18, 6.19, 7.0, 7.1; Ubuntu 24.04 (HWE 7.0)

> Would you like to add your model here? Create an issue with the "Tested Hardware" label and include these after successfully installing the patch and using the tool:
> * Your laptop's board id (you can find it in /sys/class/dmi/id/board_name)
> * Your kernel version (you can find it in /proc/version)

## Installation

### System Dependencies
You must install kernel headers and build tools for the driver patch to compile and persist across kernel updates:

* **Arch Linux / CachyOS / Manjaro:**
  ```bash
  sudo pacman -S linux-headers base-devel dkms
  # Optional (for fan cleaner feature):
  sudo pacman -S acpi_call-dkms
  ```

* **Debian / Ubuntu / Pop!_OS / Linux Mint:**
  ```bash
  sudo apt install linux-headers-$(uname -r) \
                   linux-headers-$(uname -r | sed 's/-[^-]*$/-common/') \
                   "linux-kbuild-$(uname -r | cut -d. -f1,2,3 | cut -d+ -f1)*" \
                   build-essential dkms
  # Optional (for fan cleaner feature):
  sudo apt install acpi_call-dkms
  ```
  > **Note:** Debian and Ubuntu split kernel headers into multiple packages: architecture-specific (`linux-headers-<version>-amd64`), common (`linux-headers-<version>-common`), and build scripts (`linux-kbuild-<version>`). All must be installed for out-of-tree module compilation.

* **Fedora / RHEL / Rocky Linux:**
  ```bash
  sudo dnf install kernel-devel-$(uname -r) kernel-headers gcc make dkms
  ```

* **CachyOS / Clang Kernels:** The Makefile detects if your kernel was built with Clang/LLVM and passes the correct `LLVM=1` flags to the build system. No extra configuration is needed.

---

### Choose an Installation Method

Choose one of the following: pipx/uv (recommended), Arch Linux packages, Debian packages, or clone + run from source.

### Option A: pipx or uv (recommended)

Install the app in an isolated environment. Driver sources are bundled; you can run `install-patch` from the app.

**Using pipx:**
```bash
pipx install git+https://github.com/arfelious/omen-fan-control.git
sudo omen-fan-control  status
sudo omen-fan-control-gui
```

**Using uv:**
```bash
uv tool install git+https://github.com/arfelious/omen-fan-control.git
sudo omen-fan-control  status
sudo omen-fan-control-gui
```

### Option B: Arch Linux (PKGBUILD)

Build from `arch/`. Two variants are available:

* **`omen-fan-control-dkms`** (recommended) – depends on `omen-fan-control`
  and places the driver into `/usr/src/hp-wmi-omen-1.0/` so DKMS builds it
  automatically on install and on every kernel update. This project brings
  support for boards that aren't supported by the original driver so this
  approach is the best way to ensure compatibility.
* **`omen-fan-control`** (base) – the app only. Driver sources are bundled so
  `install-patch permanent` still works, but DKMS is **not** auto-setup.
  Suitable only for kernels >= 6.20 and if your board is supported by the
  original `hp-wmi` kernel driver.

#### Option 1) DKMS variant (Recommended: app + auto DKMS)
```bash
# 1. Build the base app:
cd omen-fan-control/arch/omen-fan-control
makepkg -sf

# 2. Build the DKMS module package:
cd ../omen-fan-control-dkms
makepkg -f --nodeps

# 3. Install both packages:
sudo pacman -U ../omen-fan-control/omen-fan-control-*.pkg.tar.zst omen-fan-control-dkms-*.pkg.tar.zst
```
#### Option 2) Base app only (no DKMS auto-setup, only if board is already fully supported)
```bash
cd omen-fan-control/arch/omen-fan-control
makepkg -sf
sudo pacman -U omen-fan-control-*.pkg.tar.zst

```


### Option C: Debian / Ubuntu (deb)

Build from `deb/`. Two variants are available:

* **`omen-fan-control`** (base) – the app only with bundled driver sources.
* **`omen-fan-control-dkms`** (recommended) – depends on `omen-fan-control`
  and places the driver into `/usr/src/hp-wmi-omen-1.0/` with a postinst
  hook that runs `dkms add / build / install`.

```bash
# Build all packages
cd omen-fan-control/deb
./build.sh all

# Base install (app only)
sudo dpkg -i build/omen-fan-control_*.deb

# Or: DKMS variant (app + auto DKMS)
sudo dpkg -i build/omen-fan-control-dkms_*.deb
```

### Option D: Clone and run from source

```bash
git clone https://github.com/arfelious/omen-fan-control.git
cd omen-fan-control

# With uv (recommended for source)
uv sync
sudo uv run omen-fan-control status
sudo uv run omen-fan-control install-patch permanent
sudo uv run omen-fan-control service install
sudo uv run omen-fan-control-gui

# With pip (editable install)
pip install -e .
sudo omen-fan-control status

# Or with pip + PYTHONPATH
pip install -r requirements.txt
export PYTHONPATH=src
sudo env PYTHONPATH=src python -m omen_fan_control.cli status
```

## Usage

After installation, use `omen-fan-control` (CLI) and `omen-fan-control-gui` (GUI).
From a clone, replace with `uv run omen-fan-control` or `PYTHONPATH=src python -m omen_fan_control.cli`.

### GUI

```bash
sudo omen-fan-control-gui
```

**GUI Fan Curve:**

| <img width="400" height="300" alt="Omen Fan Control GUI" src="https://github.com/user-attachments/assets/57f1a966-d7a6-4c5f-8090-a1e947349bd9" /> |
|---|

### CLI

**Check Status:**
```bash
sudo omen-fan-control status
```

**Settings:**
```bash
omen-fan-control settings --help
omen-fan-control settings
sudo omen-fan-control options --ma-window 10 --curve-interpolation smooth
```

**Fan Control:**
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

**Temporary Settings (`--no-save`):**
Use the `--no-save` flag to apply settings to the current session only. This prevents the utility from updating your persistent configuration file and is useful for one-off manual adjustments, hooks or scripts.

> When using `--no-save` in **Manual** or **Auto** modes, the utility will automatically stop the background service to prevent it from overwriting your temporary setting. However, in **Curve** mode, the service is kept running as it is required to process the temperature data and apply the fan curve.

```bash
sudo omen-fan-control fan-control --mode manual --value 100% --no-save
```

**Detailed Information for Commands:**
Commands provide detailed information when `--help` is passed with the command:
```bash
omen-fan-control fan-control --help
```

### Install Driver Patch

```bash
# Permanent Installation (Recommended)
sudo omen-fan-control install-patch permanent

# Temporary Installation (Until Reboot)
sudo omen-fan-control install-patch temporary
```

### Install Background Service

```bash
sudo omen-fan-control service install
```

You can also install it from the settings page in the graphical interface.

## Fan Cleaning

This is currently the only Linux utility capable of recreating the fan cleaning routine. On supported laptops, it reverses fan spin direction to dislodge accumulated dust. The cleaning interval, manual cleanup, and further configuration can be done using the **Fan Cleaner** page. The page is not visible on unsupported hardware to prevent unexpected behavior.

Fan cleaning feature requires the `acpi_call` module to be loaded:
```bash
sudo modprobe acpi_call
```

If you don't have the module installed:

**Ubuntu / Debian / Pop!_OS:**
```bash
sudo apt update
sudo apt install acpi-call-dkms
sudo modprobe acpi_call
```

**Arch Linux / Manjaro / CachyOS:**
```bash
sudo pacman -S acpi_call-dkms
sudo modprobe acpi_call
```

## Related Projects

This utility is part of an ongoing effort to bring more **OMEN Gaming Hub** features to Linux. You might also want to check this project out:

[Omen RGB Linux](https://github.com/arfelious/omen-rgb-linux): Per-key RGB lighting controller with GUI and SDK for OMEN laptops on Linux.

## Uninstallation

1. **Remove Service:**
   ```bash
   sudo omen-fan-control service remove
   ```

2. **Restore Driver:**
   ```bash
   sudo omen-fan-control install-patch restore
   ```
   This restores the original `.ko` files from the backups created during installation.

3. **Uninstall Package:**
   * **pipx:** `pipx uninstall omen-fan-control`
   * **uv:** `uv tool uninstall omen-fan-control`
   * **Arch:** `sudo pacman -R omen-fan-control`
   * **Debian:** `sudo apt remove omen-fan-control`

## Disclaimer

**USE AT YOUR OWN RISK.**
Modifying kernel drivers and manipulating thermal control systems can potentially damage your hardware or cause instability. This software is provided "as is" without warranty of any kind. This was tested on my personal hardware, and the used `hp-wmi.c` is a patched and modified version of the one in the Linux kernel, so your mileage may vary.

<details>
<summary>Acknowledgements</summary>
<br>

**Probes:**
- https://github.com/alou-S/omen-fan/blob/main/docs/probes.md

**Linux 6.20 Kernel HP-WMI Driver:**
- https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c

</details>
