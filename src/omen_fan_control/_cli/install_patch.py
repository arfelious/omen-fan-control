from __future__ import annotations

import sys

import click

from . import _cmd, get_controller


@click.command()
@click.argument("install_type", required=False)
@click.option("--temp", is_flag=True, help="Legacy: Install temporarily")
@click.option("--perm", is_flag=True, help="Legacy: Install permanently")
@click.option("--restore", is_flag=True, help="Legacy: Restore original")
def install_patch(
    install_type: str | None,
    temp: bool,
    perm: bool,
    restore: bool,
) -> None:
    """Install the fan driver patch or restore original.

    INSTALL_TYPE can be:
      t, temp, temporary  : Install temporarily (until reboot)
      p, perm, permanent  : Install permanently (patches source)
      r, restore          : Restore original driver from backups
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
        click.echo("Please specify installation type: t (temp, temporary), p (perm, permanent), or r (restore).")
        click.echo(f"Example: {_cmd} install-patch temporary")
        return

    if mode == "temp":
        click.echo("Installing temporary driver...")
        success, msg = controller.install_driver_temp()
        if not success and msg == "PWM_DETECTED":
            msg_add = ""
            itype = controller.check_install_type()
            if itype == "temporary":
                msg_add = "\n(The current installation may be temporary)"
            if click.confirm(f"Driver seems to be already active/installed.{msg_add}\nForce re-install?"):
                success, msg = controller.install_driver_temp(force=True)
        click.echo(msg)
        if not success:
            sys.exit(1)

    elif mode == "perm":
        click.echo("Installing permanent driver...")
        success, msg = controller.install_driver_perm()
        if not success and msg == "PWM_DETECTED":
            msg_add = ""
            itype = controller.check_install_type()
            if itype == "temporary":
                msg_add = "\n(The current installation may be temporary)"
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
