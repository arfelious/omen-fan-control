from __future__ import annotations

import click

from . import get_controller


@click.command()
def calibrate() -> None:
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
