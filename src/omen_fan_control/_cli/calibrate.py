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
                result = e.value

            if isinstance(result, (tuple, list)):
                rpm1, rpm2 = result
                click.echo(f"\nCalibration finished.\n• Fan 1 (CPU) Max: {rpm1} RPM\n• Fan 2 (GPU) Max: {rpm2} RPM")
            else:
                click.echo(f"\nCalibration finished. Max RPM: {result}")

        finally:
            controller.config["mode"] = prev_mode
            controller.save_config()
