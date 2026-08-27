from __future__ import annotations

import time

import click

from . import get_controller


@click.command()
@click.argument("duration", required=True)
def stress(duration: str) -> None:
    """
    Run CPU stress test for specified DURATION.

    \b
    DURATION format examples:
      30s   - Run for 30 seconds
      1m    - Run for 1 minute
      5m    - Run for 5 minutes
      1h    - Run for 1 hour
    """
    controller = get_controller()

    try:
        duration_str = duration.lower().strip()
        seconds = 0
        if duration_str.endswith("s"):
            seconds = int(duration_str[:-1])
        elif duration_str.endswith("m"):
            seconds = int(duration_str[:-1]) * 60
        elif duration_str.endswith("h"):
            seconds = int(duration_str[:-1]) * 3600
        else:
            seconds = int(duration_str)

        if seconds <= 0:
            click.echo("Error: Duration must be positive.")
            return

    except ValueError:
        click.echo(f"Error: Invalid duration format '{duration}'. Use '30s', '1m', etc.")
        return

    click.echo(f"Starting CPU Stress Test for {seconds} seconds...")
    click.echo("Press Ctrl+C to stop manually.")

    if controller.start_stress_test(seconds):
        try:
            start_time = time.time()
            while time.time() - start_time < seconds:
                elapsed = int(time.time() - start_time)
                remaining = seconds - elapsed
                print(f"Time remaining: {remaining}s   ", end="\r")
                time.sleep(1)
        except KeyboardInterrupt:
            click.echo("\nStress test cancelled by user.")
        finally:
            controller.stop_stress_test()
            click.echo("\nStress test stopped.")
    else:
        click.echo("Failed to start stress test processes.")
