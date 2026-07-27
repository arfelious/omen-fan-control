from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from ..logic import FanController


def _get_invocation_name() -> str:
    arg0 = sys.argv[0] if sys.argv else ""

    if arg0.endswith("/cli.py") or arg0.endswith("/cli"):
        return "python -m omen_fan_control.cli"
    if arg0.endswith("/__main__.py") or arg0 == "-m" or " -m " in arg0:
        return "python -m omen_fan_control"
    if arg0 and "/uv" in arg0:
        return "uv run omen-fan-control"
    if arg0.endswith("/omen-fan-control"):
        return "omen-fan-control"

    if arg0 and " " not in arg0:
        base = Path(arg0).name
        known = {"omen-fan-control-cli", "omen-fan-control"}
        if base in known:
            return base

    if arg0 and not arg0.endswith((".py", ".pyc")):
        return arg0.split()[-1]

    return "omen-fan-control"


_cmd: str = _get_invocation_name()


@click.group(invoke_without_command=False)
@click.option("--config", type=click.Path(), help="Path to custom config file")
@click.option("--help-extra", is_flag=True, help="Show extra/advanced commands help")
@click.pass_context
def cli(ctx: click.Context, config: str | None, help_extra: bool) -> None:
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
        click.echo(click.style("Use --bypass-root-warning in 'omen-fan-control options' config to hide this.", dim=True))
        click.echo("", err=True)

    if not controller.config.get("bypass_patch_warning", False):
        status, board = controller.check_board_support()
        if status == "UNSUPPORTED":
            click.echo(click.style(f"WARNING: Your board '{board}' is not in the known compatible list.", fg="red"))
            click.echo(click.style("Using this tool could potentially cause system instability.", fg="red"))
            click.echo("To bypass this warning, set 'bypass_patch_warning' to true in config or toggle in GUI.")
        elif status == "POSSIBLY_SUPPORTED" and not controller.config.get("enable_experimental", False):
            click.echo(click.style(f"NOTE: Your board '{board}' is valid for experimental support.", fg="yellow"))
            click.echo(click.style("Community patches suggest it uses the Omen thermal path.", fg="yellow"))
            click.echo("You can enable experimental support in the GUI Settings or by editing config.json:")
            click.echo('  "enable_experimental": true, "thermal_profile": "omen" (or victus/victus_s)')
            click.echo("")


def get_controller() -> FanController:
    ctx = click.get_current_context()
    config_path = ctx.obj.get("config_path") if ctx.obj else None
    return FanController(config_path=config_path)


def main() -> None:
    if len(sys.argv) == 1:
        cli.main(["--help"])
    else:
        cli()


if __name__ == "__main__":
    main()
