# HP Omen Fan Control (Linux)

This tool provides fan control for HP Omen Max, Victus and Omen laptops on Linux. It includes installer for a kernel driver patch (`hp-wmi`) to expose PWM controls and a userspace utility to manage fan curves, create watchdog that sets the fan configuration periodically and a simple stress test tool to see the fan curve in effect.

## Context

This tool includes a backported `hp-wmi` driver patch from the upcoming Linux 6.20 kernel, which introduces native fan control support for many devices from the following models:
1.  **HP Omen Max**
2.  **HP Victus**
3.  **HP Omen**

The patch can be installed on versions before `6.20`.

**Reference Kernel Commit:**
[platform/x86: hp-wmi: add manual fan control for Victus S models](https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c)

This program also includes a modification that sets the max speed according to calibration if the query to get the Max RPM fails for your device.
## Tested Hardware

*   **Model:** HP OMEN MAX 16-AH0001NT (8D41)
*   **OS:** Arch Linux 6.18.6

## Installation

### Clone the repository
Clone the repository or download the latest source code from the [Releases](https://github.com/arfelious/omen-fan-control/releases) page.

```bash
git clone https://github.com/arfelious/omen-fan-control.git
cd omen-fan-control
```

### Dependencies

**1. System Dependencies**
You must install kernel headers and build tools for the driver patch to compile.
*   **Arch:** `pacman -S linux-headers base-devel`
*   **Debian/Ubuntu:** `apt install linux-headers-$(uname -r) linux-headers-$(uname -r | sed 's/-[^-]*$/-common/') "linux-kbuild-$(uname -r | cut -d. -f1,2,3 | cut -d+ -f1)*" build-essential`

    > **Note:** Debian and Ubuntu split kernel headers into multiple packages: an arch-specific one (`linux-headers-<version>-amd64`), a common one (`linux-headers-<version>-common`), and a build scripts package (`linux-kbuild-<version>`). All must be installed for the module build to succeed. 
    >
    >If you get a similar after installing the headers, try `sudo apt reinstall linux-headers-$(uname -r) linux-headers-$(uname -r | sed 's/-[^-]*$/-common/') "linux-kbuild-$(uname -r | cut -d. -f1,2,3 | cut -d+ -f1)*" build-essential` and reboot.


*   **CachyOS / Clang Kernels:** The Makefile detects if your kernel was built with Clang/LLVM and passes the correct `LLVM=1` flags to the build system. No extra configuration is needed.

**2. Python Dependencies**
You can install the required Python packages (`click`, `PyQt6`) via your package manager OR pip, preferably with a virtual environment.

*   **Option A: Package Manager**
    *   **Arch:** `pacman -S python-click python-pyqt6`
    *   **Debian/Ubuntu:** `apt install python3-click python3-pyqt6`

*   **Option B: Pip**
    ```bash
    pip install -r requirements.txt
    ```

### Install Driver Patch
You can install the modified driver temporarily (current session) or permanently (DKMS-style patch).

```bash
# Permanent Installation (Recommended)
sudo python3 omen_cli.py install-patch permanent

# Temporary Installation (Until Reboot)
sudo python3 omen_cli.py install-patch temporary
```

### Install Background Service
For proper curve control and watchdog operation, install the background service:

```bash
sudo python3 omen_cli.py service install
```

You can also install it from the settings page in the graphical interface.
## Usage
### GUI
A graphical interface is available for simpler configuration.
```bash
sudo python3 omen_gui.py
```
**GUI Fan Curve**

|<img width="400" height="300" alt="Omen Fan Control GUI" src="https://github.com/user-attachments/assets/57f1a966-d7a6-4c5f-8090-a1e947349bd9" />|
|---|


### CLI
The `omen_cli.py` script manages everything.

**Check Status:**
```bash
sudo python3 omen_cli.py status
```
**Possible Settings**
```bash
python omen_cli.py settings --help
```
**Current Settings Configuration**
```bash
python omen_cli.py settings
```

**Set Settings (Moving Average Window, etc.):**
```bash
sudo python3 omen_cli.py options --ma-window 10 --curve-interpolation smooth
```

**Manual Fan Control:**
```bash
# Set specific speed
sudo python3 omen_cli.py fan-control --mode manual --value 80%

# Set Curve Mode (requires service)
sudo python3 omen_cli.py fan-control --mode curve

# Set Auto (Default)
sudo python3 omen_cli.py fan-control --mode auto
```

**Using Custom Curves:**
```bash
sudo python3 omen_cli.py fan-control --curve-csv my_curve.csv
```
Where the csv file has values in `temp, percent` order

<br>

**Detailed Information**

Commands provide detailed information when `--help` is passed with the command
```bash
python omen_cli.py fan-control --help
```

## Uninstallation

To remove the service and restore the original kernel driver:

1.  **Remove Service:**
    ```bash
    sudo python3 omen_cli.py service remove
    ```

2.  **Restore Driver:**
    ```bash
    sudo python3 omen_cli.py install-patch restore
    ```
    This restores the original `.ko` files from the backups created during installation.

## Disclaimer

**USE AT YOUR OWN RISK.**
Modifying kernel drivers and manipulating thermal control systems can potentially damage your hardware or cause instability. This software is provided "as is" without warranty of any kind. This was tested on my personal hardware, and the used `hp-wmi.c` is a patched version of the one in the upcoming `6.20` kernel, so your mileage may vary.

<details>
<summary>Acknowledgements</summary>
<br>

**Probes:**
- https://github.com/alou-S/omen-fan/blob/main/docs/probes.md

**Linux 6.20 Kernel HP-WMI Driver:**
- https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c

</details>
