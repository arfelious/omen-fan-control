# Omen Fan Control CLI
# Copyright (C) 2026 arfelious
# SPDX-License-Identifier: GPL-3.0-or-later

import os
import sys
from pathlib import Path

import click

from . import get_data_dir
from .logic import FanController


@click.group()
@click.option("--config", type=click.Path(), help="Path to custom config file")
@click.option("--help-extra", is_flag=True, help="Show extra/advanced commands help")
@click.pass_context
def cli(ctx, config, help_extra):
    """HP Omen Fan Control CLI"""
    if help_extra:
        click.echo("Extra / Advanced Commands:")
        click.echo("  disable-bios   Disable BIOS fan control (writes to EC)")
        click.echo("  enable-bios    Enable BIOS fan control (writes to EC)")
        click.echo("\n  Note: Disabling BIOS control is usually unnecessary as the driver handles overrides.")
        ctx.exit()
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config
    controller = FanController(config_path=config)
    if os.geteuid() != 0 and not controller.config.get("bypass_root_warning", False):
        click.echo(click.style("WARNING: Running without root privileges.", fg="yellow"))
        click.echo(click.style("Most commands require root to function correctly.", fg="yellow"))
        click.echo(click.style("Use 'omen-fan-control options' to set bypass_root_warning in config to hide this.", dim=True))
        click.echo("", err=True)
    if not controller.config.get("bypass_warning", False):
        status, board = controller.check_board_support()
        if status == "UNSUPPORTED":
            click.echo(click.style(f"WARNING: Your board '{board}' is not in the known compatible list.", fg="red"))
            click.echo(click.style("Using this tool could potentially cause system instability.", fg="red"))
            click.echo("To bypass this warning, set 'bypass_warning' to true in config or toggle in GUI.")
        elif status == "POSSIBLY_SUPPORTED" and not controller.config.get("enable_experimental", False):
            click.echo(click.style(f"NOTE: Your board '{board}' is valid for experimental support.", fg="yellow"))
            click.echo(click.style("Community patches suggest it uses the Omen thermal path.", fg="yellow"))
            click.echo("You can enable experimental support in the GUI Settings or by editing config.json:")
            click.echo('  "enable_experimental": true, "thermal_profile": "omen" (or victus/victus_s)')
            click.echo("")


def get_controller():
    ctx = click.get_current_context()
    config_path = ctx.obj.get("config_path") if ctx.obj else None
    return FanController(config_path=config_path)


@cli.command()
def calibrate():
    """Run fan calibration to determine max RPM."""
    controller = get_controller()
    if click.confirm("This will spin fans at max speed for calibration. Continue?"):
        prev_mode = controller.config.get("mode", "auto")
        controller.config["mode"] = "calibration"
        controller.save_config()
        try:
            gen = controller.calibrate()
            max_rpm = 0
            try:
                while True:
                    progress = next(gen)
                    click.echo(f"Calibrating... {progress}%", nl=False)
                    click.echo("\r", nl=False)
            except StopIteration as e:
                max_rpm = e.value
            click.echo(f"\nCalibration finished. Max RPM: {max_rpm}")
        finally:
            controller.config["mode"] = prev_mode
            controller.save_config()


@cli.command()
@click.argument("install_type", required=False)
@click.option("--temp", is_flag=True, help="Legacy: Install temporarily")
@click.option("--perm", is_flag=True, help="Legacy: Install permanently")
@click.option("--restore", is_flag=True, help="Legacy: Restore original")
def install_patch(install_type, temp, perm, restore):
    """
    Install the fan driver patch or restore original.
    INSTALL_TYPE: t|temp|temporary, p|perm|permanent, r|restore
    """
    controller = get_controller()
    mode = None
    if install_type:
        install_type = install_type.lower()
        if install_type in ("t", "temp", "temporary"):
            mode = "temp"
        elif install_type in ("p", "perm", "permanent"):
            mode = "perm"
        elif install_type in ("r", "restore"):
            mode = "restore"
    if not mode:
        if temp:
            mode = "temp"
        elif perm:
            mode = "perm"
        elif restore:
            mode = "restore"
    if not mode:
        click.echo("Please specify: t (temp), p (perm), or r (restore). Example: omen-fan-control install-patch permanent")
        return
    if mode == "temp":
        click.echo("Installing temporary driver...")
        success, msg = controller.install_driver_temp()
        if not success and msg == "PWM_DETECTED":
            itype = controller.check_install_type()
            msg_add = "\n(The current installation may be temporary)" if itype == "temporary" else ""
            if click.confirm(f"Driver seems to be already active/installed.{msg_add}\nForce re-install?"):
                success, msg = controller.install_driver_temp(force=True)
        click.echo(msg)
        if not success:
            sys.exit(1)
    elif mode == "perm":
        click.echo("Installing permanent driver...")
        success, msg = controller.install_driver_perm()
        if not success and msg == "PWM_DETECTED":
            itype = controller.check_install_type()
            msg_add = "\n(The current installation may be temporary)" if itype == "temporary" else ""
            if click.confirm(f"Driver seems to be already active/installed.{msg_add}\nForce re-install?"):
                success, msg = controller.install_driver_perm(force=True)
        click.echo(msg)
        if not success:
            sys.exit(1)
    elif mode == "restore":
        click.echo("Restoring original driver...")
        success, msg = controller.restore_driver()
        click.echo(msg)
        if not success:
            sys.exit(1)


@cli.command()
@click.option("--mode", type=click.Choice(["auto", "max", "manual", "curve", "last"]), help="Fan mode. 'last' loads from config.")
@click.option("--value", required=False, help="Manual: 0-255 (PWM) or 0-100% (e.g. '50%')")
@click.option("--curve-csv", required=False, type=click.Path(exists=True), help="CSV for curve (temp,percent)")
@click.argument("action", required=False)
def fan_control(mode, value, curve_csv, action):
    """Control fan mode and speed. E.g. fan-control --mode auto; fan-control set (apply last)."""
    if mode is None:
        if curve_csv:
            mode = "curve"
        elif action == "set":
            mode = "last"
        else:
            ctx = click.get_current_context()
            click.echo(ctx.get_help())
            ctx.exit()
    controller = get_controller()
    default_conf = Path("/etc/omen-fan-control/config.json")
    if controller.is_service_running() and controller.config_path.resolve() != default_conf.resolve():
        click.echo(click.style("WARNING: Background service is active using system config.", fg="yellow"))
        click.echo(click.style(f"It may overwrite changes from {controller.config_path.name}.", fg="yellow"))
        click.echo("Suggestion: Stop the service before testing custom configs.\n")
    if mode == "last":
        mode = controller.config.get("mode", "auto")
        click.echo(f"Applying last saved mode: {mode.upper()}")
    if mode == "auto":
        controller.set_fan_mode("auto")
        click.echo("Fan set to AUTO.")
    elif mode == "max":
        controller.set_fan_mode("max")
        click.echo("Fan set to MAX.")
    elif mode == "manual":
        if not (controller.pwm1_path and controller.pwm1_path.exists()):
            click.echo("Error: Manual mode requires the kernel driver patch. Run 'omen-fan-control install-patch perm'.")
            sys.exit(1)
        if value is None:
            click.echo("Please specify --value (0-255 or 0-100%) for manual mode")
            return
        try:
            val_str = str(value).strip()
            if val_str.endswith("%"):
                percent = int(val_str[:-1])
                if not (0 <= percent <= 100):
                    click.echo("Error: Percentage must be 0-100.")
                    return
                pwm_val = int(round(percent / 100 * 255))
                click.echo(f"Setting speed to {percent}% (PWM: {pwm_val})")
            else:
                pwm_val = int(val_str)
                if not (0 <= pwm_val <= 255):
                    click.echo("Error: PWM value must be 0-255.")
                    return
                click.echo(f"Setting PWM to {pwm_val}")
            controller.config["mode"] = "manual"
            controller.config["manual_pwm"] = pwm_val
            controller.save_config()
            controller.set_fan_pwm(pwm_val)
        except ValueError:
            click.echo(f"Error: Invalid value '{value}'. Use 0-255 or '50%'.")
            return
    elif mode == "curve":
        if not (controller.pwm1_path and controller.pwm1_path.exists()):
            click.echo("Error: Curve mode requires the kernel driver patch. Run 'omen-fan-control install-patch perm'.")
            sys.exit(1)
        if curve_csv:
            points = []
            try:
                with open(curve_csv, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith("#") or "," not in line:
                            continue
                        parts = line.split(",")
                        if len(parts) >= 2:
                            temp, speed = int(parts[0].strip()), int(parts[1].strip())
                            if not (0 <= speed <= 100):
                                click.echo(f"Error: Speed {speed} must be 0-100%.")
                                return
                            points.append([temp, speed])
                if not points:
                    click.echo("Error: No valid points in CSV.")
                    return
                points.sort(key=lambda x: x[0])
                controller.config["curve"] = points
                click.echo(f"Loaded {len(points)} points from CSV.")
            except Exception as e:
                click.echo(f"Error reading CSV: {e}")
                return
        controller.config["mode"] = "curve"
        controller.save_config()
        click.echo("Curve mode enabled in config.")
        if not controller.is_service_installed():
            click.echo("WARNING: Background service is NOT installed. Curve mode needs the service.")
            click.echo("  sudo systemctl start omen-fan-control.service  or  omen-fan-control serve")
        else:
            click.echo("Service should pick up the change automatically.")


@cli.command()
def serve():
    """Run the fan control daemon (foreground). Used by systemd service."""
    import time
    controller = get_controller()
    click.echo("Starting Omen Fan Control Daemon...")
    ma_window = controller.config.get("ma_window", 5)
    temp_history = []
    watchdog_interval = controller.config.get("watchdog_interval", 90)
    last_watchdog_time = time.time()
    hysteresis_start_time = None
    last_config_mtime = 0
    while True:
        try:
            try:
                current_mtime = controller.config_path.stat().st_mtime
                if current_mtime > last_config_mtime:
                    controller.config = controller.load_config()
                    last_config_mtime = current_mtime
            except Exception:
                pass
            mode = controller.config.get("mode", "auto")
            if mode == "calibration":
                time.sleep(1)
                continue
            if time.time() - last_watchdog_time > watchdog_interval:
                last_watchdog_time = time.time()
            current_temp = controller.get_cpu_temp()
            temp_history.append(current_temp)
            if len(temp_history) > ma_window:
                temp_history.pop(0)
            avg_temp = sum(temp_history) / len(temp_history)
            if mode == "curve":
                target_pwm = controller.calculate_target_pwm(avg_temp)
                if target_pwm is not None:
                    current_rpm = controller.get_fan_speed()
                    max_rpm = controller.config.get("fan_max", 0)
                    should_apply = True
                    if max_rpm > 0:
                        target_rpm = (target_pwm / 255) * max_rpm
                        diff = abs(target_rpm - current_rpm)
                        if diff <= 200:
                            if hysteresis_start_time is None:
                                hysteresis_start_time = time.time()
                            should_apply = time.time() - hysteresis_start_time > 60
                        else:
                            hysteresis_start_time = None
                    if should_apply:
                        controller.set_fan_pwm(target_pwm)
                        hysteresis_start_time = None
            elif mode == "manual":
                manual_val = controller.config.get("manual_pwm", -1)
                if manual_val >= 0:
                    controller.set_fan_pwm(manual_val)
            elif mode == "max":
                controller.set_fan_mode("max")
            elif mode == "auto":
                controller.set_fan_mode("auto")
            time.sleep(2)
        except KeyboardInterrupt:
            click.echo("Stopping daemon...")
            break
        except Exception as e:
            click.echo(f"Error in daemon loop: {e}")
            time.sleep(5)


@cli.command()
@click.argument("duration", required=True)
def stress(duration):
    """Run CPU stress test. DURATION: 30s, 1m, 5m, 1h."""
    import time
    controller = get_controller()
    try:
        s = duration.lower().strip()
        if s.endswith("s"):
            seconds = int(s[:-1])
        elif s.endswith("m"):
            seconds = int(s[:-1]) * 60
        elif s.endswith("h"):
            seconds = int(s[:-1]) * 3600
        else:
            seconds = int(s)
        if seconds <= 0:
            click.echo("Error: Duration must be positive.")
            return
    except ValueError:
        click.echo(f"Error: Invalid duration '{duration}'. Use 30s, 1m, etc.")
        return
    click.echo(f"Starting CPU Stress Test for {seconds}s... Press Ctrl+C to stop.")
    if controller.start_stress_test(seconds):
        try:
            start = time.time()
            while time.time() - start < seconds:
                click.echo(f"Time remaining: {seconds - int(time.time() - start)}s   ", nl=False)
                click.echo("\r", nl=False)
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStress test cancelled.")
        finally:
            controller.stop_stress_test()
            click.echo("\nStress test stopped.")
    else:
        click.echo("Failed to start stress test.")


@cli.command()
@click.option("--wait-time", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--watchdog", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--ma-window", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--bypass-warning", type=click.Choice(["on", "off"]), required=False, is_flag=False, flag_value="show")
@click.option("--curve-interpolation", type=click.Choice(["smooth", "discrete"]), required=False, is_flag=False, flag_value="show")
@click.option("--enable-experimental", type=click.Choice(["on", "off"]), required=False, is_flag=False, flag_value="show")
@click.option("--thermal-profile", type=click.Choice(["omen", "victus", "victus_s"]), required=False, is_flag=False, flag_value="show")
def options(wait_time, watchdog, ma_window, bypass_warning, curve_interpolation, enable_experimental, thermal_profile):
    """Configure or view options. Run with no args to view all."""
    controller = get_controller()
    opts = [wait_time, watchdog, ma_window, bypass_warning, curve_interpolation, enable_experimental, thermal_profile]
    if all(x is None for x in opts):
        wt = controller.config.get("calibration_wait", 5)
        wd = controller.config.get("watchdog_interval", 90)
        mw = controller.config.get("ma_window", 5)
        bp = controller.config.get("bypass_patch_warning", False)
        ci = controller.config.get("curve_interpolation", "smooth")
        ee = controller.config.get("enable_experimental", False)
        tp = controller.config.get("thermal_profile", "omen")
        click.echo("Current Configuration:")
        click.echo(f"  Calibration Wait Time: {wt}s \t--wait-time")
        click.echo(f"  Watchdog Interval:     {wd}s \t--watchdog")
        click.echo(f"  MA Window (Smoothing): {mw}  \t--ma-window")
        click.echo(f"  Bypass Warning:        {'On' if bp else 'Off'} \t--bypass-warning")
        click.echo(f"  Curve Interpolation:   {ci} \t--curve-interpolation")
        click.echo(f"  Experimental Support:  {'On' if ee else 'Off'} \t--enable-experimental")
        click.echo(f"  Thermal Profile:       {tp} \t--thermal-profile")
        return
    changed = False
    if wait_time is not None:
        if wait_time == -1:
            click.echo(f"Current Calibration Wait Time: {controller.config.get('calibration_wait', 5)}s")
        elif wait_time > 0:
            controller.config["calibration_wait"] = wait_time
            changed = True
            click.echo(f"Calibration wait time set to {wait_time}s")
    if watchdog is not None:
        if watchdog == -1:
            click.echo(f"Current Watchdog Interval: {controller.config.get('watchdog_interval', 90)}s")
        elif watchdog > 0:
            controller.config["watchdog_interval"] = watchdog
            changed = True
            click.echo(f"Watchdog interval set to {watchdog}s")
    if ma_window is not None:
        if ma_window == -1:
            click.echo(f"Current MA Window: {controller.config.get('ma_window', 5)}")
        elif ma_window > 0:
            controller.config["ma_window"] = ma_window
            changed = True
            click.echo(f"MA Window set to {ma_window}")
    if bypass_warning is not None:
        if bypass_warning == "show":
            click.echo(f"Current Bypass Warning: {'On' if controller.config.get('bypass_patch_warning', False) else 'Off'}")
        else:
            controller.config["bypass_patch_warning"] = bypass_warning == "on"
            changed = True
            click.echo(f"Bypass Warning set to {'On' if controller.config['bypass_patch_warning'] else 'Off'}")
    if enable_experimental is not None:
        if enable_experimental == "show":
            click.echo(f"Current Experimental Support: {'On' if controller.config.get('enable_experimental', False) else 'Off'}")
        else:
            controller.config["enable_experimental"] = enable_experimental == "on"
            changed = True
            click.echo(f"Experimental Support set to {'On' if controller.config['enable_experimental'] else 'Off'}")
    if thermal_profile is not None:
        if thermal_profile == "show":
            click.echo(f"Current Thermal Profile: {controller.config.get('thermal_profile', 'omen')}")
        else:
            controller.config["thermal_profile"] = thermal_profile
            changed = True
            click.echo(f"Thermal Profile set to {thermal_profile}")
    if curve_interpolation is not None:
        if curve_interpolation == "show":
            click.echo(f"Current Interpolation: {controller.config.get('curve_interpolation', 'smooth')}")
        else:
            controller.config["curve_interpolation"] = curve_interpolation
            changed = True
            click.echo(f"Curve Interpolation set to {curve_interpolation}")
    if changed:
        controller.save_config()


@cli.group()
def service():
    """Manage background service"""
    pass


@service.command(name="install")
def install_service_cmd():
    """Install and enable the background service"""
    controller = get_controller()
    click.echo("Installing background service...")
    success, msg = controller.create_service()
    click.echo(msg)


@service.command(name="remove")
def remove_service_cmd():
    """Stop and remove the background service"""
    controller = get_controller()
    click.echo("Removing background service...")
    success, msg = controller.remove_service()
    click.echo(msg)


@service.command(name="restart")
def restart_service_cmd():
    """Restart the background service"""
    controller = get_controller()
    click.echo("Restarting background service...")
    success, msg = controller.restart_service()
    click.echo(msg)


@service.command(name="status")
def service_status_cmd():
    """Check service status"""
    controller = get_controller()
    click.echo(f"Service Installed: {'Yes' if controller.is_service_installed() else 'No'}")
    click.echo(f"Service Running:   {'Yes' if controller.is_service_running() else 'No'}")


@cli.command()
def status():
    """Show system status (Temps, Fan, Service)"""
    controller = get_controller()
    is_running = controller.is_service_running()
    status_str = click.style("RUNNING", fg="green") if is_running else click.style("STOPPED", fg="red")
    if not controller.is_service_installed():
        status_str = click.style("NOT INSTALLED", fg="yellow")
    click.echo(f"Service Status:    {status_str}")
    install_type = controller.check_install_type()
    type_str = "None"
    if install_type == "permanent":
        type_str = click.style("Permanent", fg="green")
    elif install_type == "temporary":
        type_str = click.style("Temporary (Session)", fg="yellow")
    click.echo(f"Driver Install:    {type_str}")
    mode = "Unknown"
    try:
        enable = controller.read_sys_file(controller.pwm1_enable_path)
        if enable == "0":
            mode = "Max (0)"
        elif enable == "1":
            if controller.is_service_running():
                cm = controller.config.get("mode", "manual")
                mode = "Curve (Service)" if cm == "curve" else f"Manual Fixed ({controller.config.get('manual_pwm', 0)})"
            else:
                mode = "Manual (1)"
        elif enable == "2":
            mode = "Auto (2)"
        else:
            mode = f"Unknown ({enable})"
    except Exception:
        mode = "N/A"
    click.echo(f"Driver Mode:       {mode}")
    click.echo(f"Fan Speed:         {controller.get_fan_speed()} RPM")
    click.echo(f"CPU Package Temp:  {controller.get_cpu_temp()}°C")
    click.echo("\nCore Temperatures:")
    for label, temp in controller.get_all_core_temps() or []:
        click.echo(f"  {label:<15} {temp}°C")


@cli.command(hidden=True)
def disable_bios():
    """Disable BIOS fan control (Enable Manual Mode)"""
    controller = get_controller()
    if click.confirm("This will write to EC registers to disable BIOS fan control. Continue?"):
        if controller.set_bios_control(False):
            click.echo("BIOS control disabled (Manual mode enabled).")
        else:
            click.echo("Failed to disable BIOS control.")


@cli.command(hidden=True)
def enable_bios():
    """Enable BIOS fan control"""
    controller = get_controller()
    if controller.set_bios_control(True):
        click.echo("BIOS control enabled.")
    else:
        click.echo("Failed to enable BIOS control.")


@cli.command()
@click.option("--wait-time", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--watchdog", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--ma-window", type=int, required=False, is_flag=False, flag_value=-1)
@click.option("--bypass-warning", type=click.Choice(["on", "off"]), required=False, is_flag=False, flag_value="show")
@click.option("--curve-interpolation", type=click.Choice(["smooth", "discrete"]), required=False, is_flag=False, flag_value="show")
@click.pass_context
def settings(ctx, wait_time, watchdog, ma_window, bypass_warning, curve_interpolation):
    """Alias for options"""
    ctx.invoke(options, wait_time=wait_time, watchdog=watchdog, ma_window=ma_window, bypass_warning=bypass_warning, curve_interpolation=curve_interpolation)


@cli.command()
def license():
    """Show license"""
    license_path = get_data_dir() / "LICENSE.md"
    try:
        click.echo(license_path.read_text())
    except Exception as e:
        click.echo("This program is GPL-3.0-or-later licensed.")
        click.echo(f"(Error loading LICENSE: {e})")


@cli.command()
def about():
    """Show about information"""
    click.echo("HP Omen Fan Control")
    click.echo("Version 1.0")
    click.echo("Copyright © 2026 Arfelious")
    click.echo("\nCustom fan control for HP Omen laptops on Linux.")


@cli.command()
def acknowledgements():
    """Show acknowledgements"""
    click.echo("\nAcknowledgements:\n")
    click.echo("Probes: https://github.com/alou-S/omen-fan/blob/main/docs/probes.md")
    click.echo("Linux 6.20 HP-WMI: https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c")
    click.echo("")


def main():
    if len(sys.argv) == 1:
        cli.main(["--help"])
    else:
        cli()


if __name__ == "__main__":
    main()
