#!/usr/bin/env python3
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

from ._cli import cli, get_controller
import click
import sys
import time
from . import get_data_dir



@cli.command()
@click.option('--wait-time', type=int, required=False, is_flag=False, flag_value=-1, help="Time to wait during calibration (seconds). No arg shows current.")
@click.option('--watchdog', type=int, required=False, is_flag=False, flag_value=-1, help="Watchdog interval (seconds). No arg shows current.")
@click.option('--ma-window', type=int, required=False, is_flag=False, flag_value=-1, help="Moving Average Window size. No arg shows current.")
@click.option('--bypass-warning', type=click.Choice(['on', 'off']), required=False, is_flag=False, flag_value='show', help="Bypass driver patch warning. No arg shows current.")
@click.option('--curve-interpolation', type=click.Choice(['smooth', 'discrete']), required=False, is_flag=False, flag_value='show', help="Curve interpolation mode. No arg shows current.")
@click.option('--enable-experimental', type=click.Choice(['on', 'off']), required=False, is_flag=False, flag_value='show', help="Enable experimental board support. No arg shows current.")
@click.option('--thermal-profile', type=click.Choice(['omen', 'victus', 'victus_s']), required=False, is_flag=False, flag_value='show', help="Set thermal profile for exp. support. No arg shows current.")
def options(wait_time, watchdog, ma_window, bypass_patch_warning, curve_interpolation, enable_experimental, thermal_profile):
    """
    Configure or view options.
    Run without arguments to view all current settings.
    Run with flag (e.g. --wait-time) to view specific setting.
    Run with flag and value (e.g. --wait-time 10) to set value.
    """
    controller = get_controller()
    
    if all(x is None for x in [wait_time, watchdog, ma_window, bypass_patch_warning, curve_interpolation]):
        wt = controller.config.get('calibration_wait', 5)
        wd = controller.config.get('watchdog_interval', 90)
        mw = controller.config.get('ma_window', 5)
        bp = controller.config.get('bypass_patch_warning', False)
        ci = controller.config.get('curve_interpolation', 'smooth')
        ee = controller.config.get('enable_experimental', False)
        tp = controller.config.get('thermal_profile', 'omen')
        
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
            val = controller.config.get('calibration_wait', 5)
            click.echo(f"Current Calibration Wait Time: {val}s")
        elif wait_time > 0:
            controller.config['calibration_wait'] = wait_time
            changed = True
            click.echo(f"Calibration wait time set to {wait_time}s")
        else:
            click.echo("Error: Wait time must be positive.")
    
    if watchdog is not None:
        if watchdog == -1:
            val = controller.config.get('watchdog_interval', 90)
            click.echo(f"Current Watchdog Interval: {val}s")
        elif watchdog > 0:
            controller.config['watchdog_interval'] = watchdog
            changed = True
            click.echo(f"Watchdog interval set to {watchdog}s")
        else:
            click.echo("Error: Watchdog interval must be positive.")

    if ma_window is not None:
        if ma_window == -1:
            val = controller.config.get('ma_window', 5)
            click.echo(f"Current MA Window: {val}")
        elif ma_window > 0:
            controller.config['ma_window'] = ma_window
            changed = True
            click.echo(f"MA Window set to {ma_window}")
        else:
            click.echo("Error: MA Window must be positive.")
    
    if bypass_patch_warning is not None:
        if bypass_patch_warning == 'show':
            val = controller.config.get('bypass_patch_warning', False)
            click.echo(f"Current Bypass Warning: {'On' if val else 'Off'}")
        else:
            is_on = (bypass_patch_warning == 'on')
            controller.config['bypass_patch_warning'] = is_on
            changed = True
            click.echo(f"Bypass Warning set to {'On' if is_on else 'Off'}")

    if enable_experimental is not None:
        if enable_experimental == 'show':
             val = controller.config.get('enable_experimental', False)
             click.echo(f"Current Experimental Support: {'On' if val else 'Off'}")
        else:
             is_on = (enable_experimental == 'on')
             controller.config['enable_experimental'] = is_on
             changed = True
             click.echo(f"Experimental Support set to {'On' if is_on else 'Off'}")

    if thermal_profile is not None:
        if thermal_profile == 'show':
             val = controller.config.get('thermal_profile', 'omen')
             click.echo(f"Current Thermal Profile: {val}")
        else:
             controller.config['thermal_profile'] = thermal_profile
             changed = True
             click.echo(f"Thermal Profile set to {thermal_profile}")

    if curve_interpolation is not None:
        if curve_interpolation == 'show':
             val = controller.config.get('curve_interpolation', 'smooth')
             click.echo(f"Current Interpolation: {val}")
        else:
             controller.config['curve_interpolation'] = curve_interpolation
             changed = True
             click.echo(f"Curve Interpolation set to {curve_interpolation}")
        
    if changed:
        controller.save_config()

@cli.group()
def cleaner():
    """Manage Fan Cleaner (Reverse fans for dust removal)"""
    pass

@cleaner.command("start")
@click.option('--background', '-b', is_flag=True, help="Run cleaning cycle in background without waiting")
def cleaner_start(background):
    """Start manual fan cleaning cycle immediately"""
    controller = get_controller()
    if not controller.check_fan_cleaner_capability():
        click.echo("Error: Fan cleaning hardware support not detected on this system (/proc/acpi/call required).")
        return
    click.echo("Initiating fan cleaning cycle...")
    success, msg = controller.start_fan_cleaning()
    if not success:
        click.echo(f"Error starting fan cleaning: {msg}")
        return

    click.echo("Fan cleaning started successfully!")

    if background:
        click.echo("Running in background. Use 'omen-fan-control cleaner status' to monitor progress.")
        return

    dur = controller.config.get("cleaner_duration", 30)
    click.echo(f"Cleaning in progress ({dur}s)... Press Ctrl+C to stop early.")
    try:
        start_time = time.time()
        while time.time() - start_time < dur:
            if not controller.config.get("cleaner_in_progress", False):
                break
            rem = max(0, int(dur - (time.time() - start_time)))
            print(f"Time remaining: {rem}s   ", end='\r')
            time.sleep(1)
        click.echo("\nFan cleaning cycle completed.")
    except KeyboardInterrupt:
        click.echo("\nStopping fan cleaning cycle...")
    finally:
        controller.stop_fan_cleaning()

@cleaner.command("stop")
def cleaner_stop():
    """Stop fan cleaning immediately and restore forward mode"""
    controller = get_controller()
    click.echo("Stopping fan cleaning and restoring forward mode...")
    controller.emergency_stop_fan_cleaning()
    click.echo("Fan cleaning stopped.")

@cleaner.command("enable")
def cleaner_enable():
    """Enable automatic periodic fan cleaning"""
    controller = get_controller()
    controller.config["cleaner_enabled"] = True
    controller.save_config()
    click.echo("Automatic fan cleaner enabled.")

@cleaner.command("disable")
def cleaner_disable():
    """Disable automatic periodic fan cleaning"""
    controller = get_controller()
    controller.config["cleaner_enabled"] = False
    controller.save_config()
    click.echo("Automatic fan cleaner disabled.")

@cleaner.command("status")
def cleaner_status():
    """Show current fan cleaning status and configuration"""
    controller = get_controller()
    supported = controller.check_fan_cleaner_capability()
    enabled = controller.config.get("cleaner_enabled", False)
    in_progress = controller.config.get("cleaner_in_progress", False)
    interval = controller.config.get("cleaner_interval", 14400)
    duration = controller.config.get("cleaner_duration", 30)
    last_run = controller.config.get("cleaner_last_run", 0)

    click.echo(f"Hardware Support:   {'Yes' if supported else 'No'}")
    click.echo(f"Automatic Cleaner:  {'Enabled' if enabled else 'Disabled'}")
    click.echo(f"Cleaner Status:     {'Active (Reverse)' if in_progress else 'Idle (Forward)'}")
    click.echo(f"Cleaning Interval:  {interval/3600:.1f} hours ({interval}s)")
    click.echo(f"Cleaning Duration:  {duration} seconds")
    if last_run > 0:
        elapsed_min = int((time.time() - last_run) / 60)
        click.echo(f"Last Cleaning Run:  {elapsed_min} minutes ago")
    else:
        click.echo("Last Cleaning Run:  Never")

@cleaner.command("logs")
@click.option('--lines', default=20, help="Number of recent log lines to display")
def cleaner_logs(lines):
    """Show recent fan cleaner diagnostic logs"""
    controller = get_controller()
    logs = controller.get_cleaner_logs(max_lines=lines)
    if logs:
        click.echo(logs)
    else:
        click.echo("No cleaner logs found.")

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

@service.command(name="start")
def start_service_cmd():
    """Start the background service"""
    controller = get_controller()
    click.echo("Starting background service...")
    success, msg = controller.start_service()
    click.echo(msg)

@service.command(name="stop")
def stop_service_cmd():
    """Stop the background service"""
    controller = get_controller()
    click.echo("Stopping background service...")
    success, msg = controller.stop_service()
    click.echo(msg)
    
@service.command(name="enable-shutdown-hook")
def enable_shutdown_hook_cmd():
    """Enable fan cleanup on shutdown (sets fans to 30%)"""
    controller = get_controller()
    success, msg = controller.create_shutdown_service()
    click.echo(msg)

@service.command(name="disable-shutdown-hook")
def disable_shutdown_hook_cmd():
    """Disable fan cleanup on shutdown"""
    controller = get_controller()
    success, msg = controller.remove_shutdown_service()
    click.echo(msg)
    
@service.command(name="status")
def service_status_cmd():
    """Check service status"""
    controller = get_controller()
    installed = controller.is_service_installed()
    running = controller.is_service_running()
    
    click.echo(f"Service Installed: {'Yes' if installed else 'No'}")
    click.echo(f"Service Running:   {'Yes' if running else 'No'}")

@cli.command()
def status():
    """Show comprehensive system status (Temps, Fan, Service)"""
    controller = get_controller()
    
    # 1. Service Status
    is_running = controller.is_service_running()
    status_str = click.style("RUNNING", fg="green") if is_running else click.style("STOPPED", fg="red")
    if not controller.is_service_installed():
        status_str = click.style("NOT INSTALLED", fg="yellow")
    click.echo(f"Service Status:    {status_str}")
    
    # Shutdown Hook
    is_hook_enabled = controller.is_shutdown_service_enabled()
    hook_str = click.style("ENABLED", fg="green") if is_hook_enabled else click.style("DISABLED", fg="red")
    click.echo(f"Shutdown Hook:     {hook_str}")
    
    # Installation Type
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
                config_mode = controller.config.get("mode", "manual")
                if config_mode == "curve":
                    mode = "Curve (Service)"
                elif config_mode == "manual":
                    val = controller.config.get("manual_pwm", 0)
                    mode = f"Manual Fixed ({val})"
                else:
                    mode = f"Manual (Service: {config_mode})"
            else:
                mode = "Manual (1)"
        elif enable == "2":
            mode = "Auto (2)"
        else:
            mode = f"Unknown ({enable})"
    except Exception:
        mode = "N/A"
    click.echo(f"Driver Mode:       {mode}")
    
    # 3. Fan Speed
    rpm = controller.get_fan_speed()
    click.echo(f"Fan Speed:         {rpm} RPM")
    
    # 4. Temperatures
    pkg_temp = controller.get_cpu_temp()
    click.echo(f"CPU Package Temp:  {pkg_temp}°C")
    
    click.echo("\nCore Temperatures:")
    cores = controller.get_all_core_temps()
    if cores:
        for label, temp in cores:
             click.echo(f"  {label:<15} {temp}°C")
    else:
        click.echo("  (No core temp sensors found)")

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
    """Enable BIOS fan control (Disable Manual Mode)"""
    controller = get_controller()
    if controller.set_bios_control(True):
         click.echo("BIOS control enabled (Manual mode disabled).")
    else:
         click.echo("Failed to enable BIOS control.")

@cli.command()
@click.option('--wait-time', type=int, required=False, is_flag=False, flag_value=-1, help="Time to wait during calibration (seconds). No arg shows current.")
@click.option('--watchdog', type=int, required=False, is_flag=False, flag_value=-1, help="Watchdog interval (seconds). No arg shows current.")
@click.option('--ma-window', type=int, required=False, is_flag=False, flag_value=-1, help="Moving Average Window size. No arg shows current.")
@click.option('--bypass-warning', type=click.Choice(['on', 'off']), required=False, is_flag=False, flag_value='show', help="Bypass driver patch warning. No arg shows current.")
@click.option('--curve-interpolation', type=click.Choice(['smooth', 'discrete']), required=False, is_flag=False, flag_value='show', help="Curve interpolation mode. No arg shows current.")
@click.pass_context
def settings(ctx, wait_time, watchdog, ma_window, bypass_patch_warning, curve_interpolation):
    """Alias for options"""
    ctx.invoke(options, wait_time=wait_time, watchdog=watchdog, ma_window=ma_window, bypass_patch_warning=bypass_patch_warning, curve_interpolation=curve_interpolation)

@cli.command()
def license():
    """Show license"""
    try:
        with open(get_data_dir() / "LICENSE.md", "r") as f:
            content = f.read()
        click.echo(content)
    except Exception as e:
        click.echo("This program is GPLv3 Licensed.")
        click.echo("You should have received a copy of the full license text with this program.")
        click.echo(f"\n(Error loading LICENSE.md: {e})")

@cli.command()
def about():
    """Show about information"""
    click.echo("HP Omen Fan Control")
    click.echo("Version 1.0")
    click.echo("Copyright © 2026 Arfelious")
    click.echo("\nCustom fan control implementation for HP Omen laptops on Linux.")

@cli.command()
def acknowledgements():
    """Show acknowledgements"""
    click.echo("\nAcknowledgements:\n")
    click.echo("Probes:")
    click.echo("  https://github.com/alou-S/omen-fan/blob/main/docs/probes.md")
    click.echo("\nLinux 6.20 Kernel HP-WMI Driver:")
    click.echo("  https://git.kernel.org/pub/scm/linux/kernel/git/pdx86/platform-drivers-x86.git/commit/?h=for-next&id=46be1453e6e61884b4840a768d1e8ffaf01a4c1c")
    click.echo("")

def main():
    if len(sys.argv) == 1:
        cli.main(['--help'])
    else:
        cli()

if __name__ == '__main__':
    main()
