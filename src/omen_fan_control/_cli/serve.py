from __future__ import annotations

import threading
import time

import click

from .._constants import VOLATILE_CONFIG_FILE
from . import get_controller


@click.command()
def serve() -> None:
    """Run the fan control daemon (foreground). Used by systemd service."""
    controller = get_controller()
    click.echo("Starting Omen Fan Control Daemon...")

    try:
        if controller.is_reverse_mode_active():
            click.echo("Recovery: Reverse mode detected on daemon startup. Initiating stop sequence...")
            controller.stop_fan_cleaning()
    except Exception as e:
        click.echo(f"Startup reverse mode check failed: {e}")

    ma_window = controller.config.get("ma_window", 5)
    initial_temp = controller.get_reference_temp() or 40.0

    # Half-buffer warmup: prefill floor(ma_window / 2) with baseline idle temp
    # to dilute boot-time CPU bursts without overcrowding large windows.
    temp_history: list[float] = []
    if initial_temp < 80.0:
        seed_temp = min(float(initial_temp), 45.0)
        prefill_count = int(ma_window) // 2
        temp_history = [seed_temp] * prefill_count

    watchdog_interval = controller.config.get("watchdog_interval", 90)
    last_watchdog_time = time.time()
    hysteresis_start_time: float | None = None

    daemon_start_time = time.time()

    last_config_mtime: float = 0
    last_volatile_mtime: float = 0

    while True:
        try:
            try:
                current_mtime = controller.config_path.stat().st_mtime
                current_v_mtime = 0.0
                if VOLATILE_CONFIG_FILE.exists():
                    current_v_mtime = VOLATILE_CONFIG_FILE.stat().st_mtime

                if current_mtime > last_config_mtime or current_v_mtime > last_volatile_mtime:
                    controller.config = controller.load_config()
                    last_config_mtime = controller.config_path.stat().st_mtime if controller.config_path.exists() else 0
                    last_volatile_mtime = VOLATILE_CONFIG_FILE.stat().st_mtime if VOLATILE_CONFIG_FILE.exists() else 0
                    print("Configuration reloaded from disk.")
            except Exception:
                pass

            mode = controller.config.get("mode", "auto")

            if mode == "calibration":
                time.sleep(1)
                continue

            if time.time() - last_watchdog_time > watchdog_interval:
                last_watchdog_time = time.time()

            current_temp = controller.get_reference_temp()

            cleaner_active = controller.config.get("cleaner_in_progress", False) or controller.config.get("cleaner_transitioning", False)
            if cleaner_active:
                cleaner_in_progress = controller.config.get("cleaner_in_progress", False)
                if cleaner_in_progress:
                    if current_temp is not None and current_temp > 70:
                        click.echo(f"WARNING: CPU Temp reached {current_temp}°C (> 70°C) during fan cleaning. Aborting immediately!")
                        controller.stop_fan_cleaning()
                    else:
                        start_time = controller.config.get("cleaner_start_time", 0)
                        if start_time and time.time() - start_time >= 30:
                            click.echo("Fan cleaning cycle completed normally.")
                            controller.stop_fan_cleaning()
                time.sleep(1)
                continue

            cleaner_enabled = controller.config.get("cleaner_enabled", False)
            if cleaner_enabled:
                raw_interval = controller.config.get("cleaner_interval", 14400)
                interval = max(raw_interval, 300)
                last_run = controller.config.get("cleaner_last_run", 0)

                if last_run == 0 or (daemon_start_time - last_run >= interval):
                    due = (time.time() - daemon_start_time) >= interval
                else:
                    due = (time.time() - last_run) >= interval

                if due:
                    if current_temp is not None and current_temp <= 70:
                        click.echo(f"Triggering automatic fan cleaning cycle (interval: {interval}s)...")
                        success, msg = controller.start_fan_cleaning()
                        if success:
                            def _auto_stop_cleaner() -> None:
                                time.sleep(30)
                                if controller.config.get("cleaner_in_progress", False):
                                    controller.stop_fan_cleaning()
                            threading.Thread(target=_auto_stop_cleaner, daemon=True).start()
                        else:
                            click.echo(f"Failed to start automatic fan cleaning: {msg}")

            ma_window = controller.config.get("ma_window", 5)
            if current_temp is not None:
                temp_history.append(float(current_temp))
            if len(temp_history) > ma_window:
                temp_history.pop(0)
            avg_temp = sum(temp_history) / len(temp_history) if temp_history else (float(current_temp) if current_temp else 40.0)

            gpu_temp = controller.get_gpu_temp()

            if mode == "curve":
                target_cpu_pwm, target_gpu_pwm = controller.calculate_dual_target_pwm(avg_temp, gpu_temp)
                current_rpm = controller.get_fan_speed()
                max_rpm = controller.get_effective_fan_max()

                should_apply = True

                if max_rpm > 0:
                    target_rpm = (target_cpu_pwm / 255) * max_rpm
                    diff = abs(target_rpm - current_rpm)

                    if diff <= 200:
                        if hysteresis_start_time is None:
                            hysteresis_start_time = time.time()

                        if time.time() - hysteresis_start_time > 60:
                            should_apply = True
                        else:
                            should_apply = False
                    else:
                        hysteresis_start_time = None
                        should_apply = True

                if should_apply:
                    controller.set_fan_pwm(target_cpu_pwm, target_gpu_pwm)
                    hysteresis_start_time = None

            elif mode == "manual":
                cpu_pwm, gpu_pwm = controller.get_dual_manual_pwm()
                controller.set_fan_pwm(cpu_pwm, gpu_pwm)

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
