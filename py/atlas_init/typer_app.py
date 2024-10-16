import logging
import os
import sys
from functools import partial

import typer

from atlas_init import running_in_repo
from atlas_init.cli_cfn.app import app as app_cfn
from atlas_init.cli_tf.app import app as app_tf
from atlas_init.settings.env_vars import (
    DEFAULT_PROFILE,
    AtlasInitSettings,
    as_env_var_name,
    env_var_names,
)
from atlas_init.settings.rich_utils import configure_logging, hide_secrets

logger = logging.getLogger(__name__)
app = typer.Typer(name="atlas_init", invoke_without_command=True, no_args_is_help=True)
app.add_typer(app_cfn, name="cfn")
app.add_typer(app_tf, name="tf")

app_command = partial(
    app.command,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


def extra_root_commands():
    from atlas_init.cli_root import trigger

    assert trigger


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    log_level: str = typer.Option("INFO", help="use one of [INFO, WARNING, ERROR, CRITICAL]"),
    profile: str = typer.Option(
        DEFAULT_PROFILE,
        "-p",
        "--profile",
        envvar=env_var_names("profile"),
        help="used to load .env_manual, store terraform state and variables, and dump .env files.",
    ),
    project_name: str = typer.Option(
        "",
        "--project",
        envvar=env_var_names("project_name"),
        help="atlas project name to create",
    ),
    show_secrets: bool = typer.Option(False, help="show secrets in the logs"),
):
    explicit_env_vars: dict[str, str] = {}
    if project_name != "":
        explicit_env_vars[as_env_var_name("project_name")] = project_name
    log_handler = configure_logging(log_level)
    logger.info(f"running in repo: {running_in_repo()} python location:{sys.executable}")
    missing_env_vars, ambiguous_env_vars = AtlasInitSettings.check_env_vars(
        profile,
        required_extra_fields=["project_name"],
        explicit_env_vars=explicit_env_vars,
    )
    if missing_env_vars:
        typer.echo(f"missing env_vars: {missing_env_vars}")
    if ambiguous_env_vars:
        typer.echo(
            f"amiguous env_vars: {missing_env_vars} (specified both in cli & in .env-manual file with different values)"
        )
    if missing_env_vars or ambiguous_env_vars:
        raise typer.Exit(1)
    if not show_secrets:
        hide_secrets(log_handler, {**os.environ})
    command = ctx.invoked_subcommand
    logger.info(f"in the app callback, log-level: {log_level}, command: {command}")
