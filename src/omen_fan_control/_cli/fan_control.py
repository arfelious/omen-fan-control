from __future__ import annotations

import sys
from pathlib import Path

import click

from . import _cmd, get_controller


@click.command()
@click.option("--mode", type=click.Choice(["auto", "max", "manual", "curve", "last"]), help="Set fan mode. 'last' loads from config.")
@click.option("--value", required=False, help="Manual value: 0-255 (PWM) or 0-100% (e.g. '50%')")
@click.option("--curve-csv", required=False, type=click.Path(exists=True), help="CSV file for curve mode (format: temp,percent)")
@click.option("--no-save", is_flag=True, help="Apply changes temporarily without saving to config.")
@click.option("--source", hidden=True, help="Internal use: Identify the source of the config change.")
@click.argument("action", required=False)
def fan_control(
    mode: str | None,
    value: str | None,
    curve_csv: str | None,
    no_save: bool,
    source: str | None,
    action: str | None,
) -> None:
    """Control fan mode and speed.

    Usage:
      fan-control --mode auto
      fan-control set  (Applies last saved mode)
      fan-control --mode manual --value 50% --no-save (Temporary)
    """
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
    service_active = controller.is_service_running()

    if service_active and controller.config_path.resolve() != default_conf.resolve() and not no_save:
        click.echo(click.style("WARNING: Background service is active using system config.", fg="yellow"))
        click.echo(click.style(f"It will likely overwrite your changes from {controller.config_path.name} immediately.", fg="yellow"))
        click.echo(f"Suggestion: Stop the service ('{_cmd} service stop') before testing custom configs.\n")

    if mode == "last":
        mode = controller.config.get("mode", "auto")
        click.echo(f"Applying last saved mode: {mode.upper()}")

    if no_save:
        if mode == "curve":
            if not service_active:
                click.echo(click.style("WARNING: Service is NOT running. Curve mode requires the service.", fg="yellow"))
                click.echo("Changes will be written to volatile config but won't take effect until service starts.")
        else:
            if service_active:
                click.echo("Stopping service for temporary manual control...")
                controller.stop_service()

    if mode == "auto":
        controller.set_fan_mode("auto")
        controller.config["mode"] = "auto"
        controller.save_config(volatile=no_save, source=source)
        click.echo("Fan set to AUTO.")
    elif mode == "max":
        controller.set_fan_mode("max")
        controller.config["mode"] = "max"
        controller.save_config(volatile=no_save, source=source)
        click.echo("Fan set to MAX.")
    elif mode == "manual":
        has_driver = controller.pwm1_path and controller.pwm1_path.exists()
        if not has_driver:
            click.echo("Error: Manual mode requires the kernel driver patch (pwm1 not found).")
            click.echo(f"Run '{_cmd} install-patch perm' to install it.")
            sys.exit(1)

        if value is None:
            click.echo("Please specify --value (0-255 or 0-100%) for manual mode")
            return

        try:
            pwm_val = 0
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
        except ValueError:
            click.echo(f"Error: Invalid --value '{value}'. Use 0-255 or 0-100%.")
            return

        controller.set_fan_pwm(pwm_val)
        controller.config["mode"] = "manual"
        controller.config["manual_pwm"] = pwm_val
        controller.save_config(volatile=no_save, source=source)

    elif mode == "curve":
        has_driver = controller.pwm1_path and controller.pwm1_path.exists()
        if not has_driver:
            click.echo("Error: Curve mode requires the kernel driver patch (pwm1 not found).")
            click.echo(f"Run '{_cmd} install-patch perm' to install it.")
            sys.exit(1)

        if not service_active:
            click.echo(click.style("WARNING: Service must be running for curve mode to work.", fg="yellow"))
            click.echo(f"Start it with: {_cmd} service start")

        controller.config["mode"] = "curve"
        controller.save_config(volatile=no_save, source=source)
        click.echo("Fan set to CURVE mode.")

        if curve_csv:
            try:
                points = []
                with open(curve_csv) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = line.split(",")
                            if len(parts) == 2:
                                temp = int(parts[0].strip())
                                pct = int(parts[1].strip())
                                points.append([temp, pct])
                if points:
                    controller.config["curve"] = points
                    controller.save_config(volatile=no_save, source=source)
                    click.echo(f"Loaded {len(points)} curve points from {curve_csv}.")
                else:
                    click.echo("Warning: No valid curve points found in CSV.")
            except Exception as e:
                click.echo(f"Error loading curve CSV: {e}")
