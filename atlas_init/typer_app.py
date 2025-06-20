import logging
import os
import sys
from functools import partial

import typer

from atlas_init import running_in_repo
from atlas_init.cli_cfn.app import app as app_cfn
from atlas_init.cli_helper.run import add_to_clipboard
from atlas_init.cli_root import set_dry_run
from atlas_init.cli_tf.app import app as app_tf
from atlas_init.cloud.aws import download_from_s3, upload_to_s3
from atlas_init.settings.env_vars import (
    DEFAULT_PROFILE,
    ENV_CLIPBOARD_COPY,
    ENV_PROFILE,
    ENV_PROJECT_NAME,
    ENV_S3_PROFILE_BUCKET,
    init_settings,
)

logger = logging.getLogger(__name__)


def sync_on_done(return_value, s3_profile_bucket: str = "", use_clipboard: str = "", **kwargs):
    logger.debug(f"sync_on_done return_value={return_value} and {kwargs}")
    settings = init_settings(skip_ambiguous_check=True)
    if s3_profile_bucket:
        logger.info(f"using s3 bucket for profile sync: {s3_profile_bucket}")
        upload_to_s3(settings.profile_dir, s3_profile_bucket)
    if use_clipboard:
        settings = settings or init_settings()
        match use_clipboard:
            case "manual":
                env_path = settings.env_file_manual
            case _:
                env_path = settings.env_vars_generated
        if env_path.exists():
            clipboard_content = "\n".join(f"export {line}" for line in env_path.read_text().splitlines())
            add_to_clipboard(clipboard_content, logger)
            logger.info(f"loaded env-vars from {env_path} to clipboard ✅")


app = typer.Typer(
    name="atlas_init",
    invoke_without_command=True,
    no_args_is_help=True,
    result_callback=sync_on_done,
)
app.add_typer(app_cfn, name="cfn")
app.add_typer(app_tf, name="tf")

app_command = partial(
    app.command,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


def extra_root_commands():
    from atlas_init.cli_root import go_test, trigger, mms_released

    assert trigger
    assert go_test
    assert mms_released


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    log_level: str = typer.Option("INFO", help="use one of [INFO, WARNING, ERROR, CRITICAL]"),
    profile: str = typer.Option(
        DEFAULT_PROFILE,
        "-p",
        "--profile",
        envvar=ENV_PROFILE,
        help="used to load .env_manual, store terraform state and variables, and dump .env files.",
    ),
    project_name: str = typer.Option(
        "",
        "--project",
        envvar=ENV_PROJECT_NAME,
        help="atlas project name to create",
    ),
    show_secrets: bool = typer.Option(False, help="show secrets in the logs"),
    dry_run: bool = typer.Option(False, help="dry-run mode"),
    s3_profile_bucket: str = typer.Option(
        "",
        "-s3",
        "--s3-profile-bucket",
        help="s3 bucket to store profiles will be synced before and after the command",
        envvar=ENV_S3_PROFILE_BUCKET,
    ),
    use_clipboard: str = typer.Option(
        "",
        help="add env-vars to clipboard, manual=.env-manual file, other value=.env-generated file",
        envvar=ENV_CLIPBOARD_COPY,
    ),
):
    set_dry_run(dry_run)
    if profile != DEFAULT_PROFILE:
        os.environ[ENV_PROFILE] = profile
    if project_name != "":
        os.environ[ENV_PROJECT_NAME] = project_name
    if use_clipboard:
        os.environ[ENV_CLIPBOARD_COPY] = use_clipboard
    is_running_in_repo = running_in_repo()
    logger.info(f"running in atlas-init repo: {is_running_in_repo} python location:{sys.executable}")
    logger.info(f"in the app callback, log-level: {log_level}, command: {format_cmd(ctx)}")
    if s3_bucket := s3_profile_bucket:
        logger.info(f"using s3 bucket for profile sync: {s3_bucket}")
        settings = init_settings()
        download_from_s3(settings.profile_dir, s3_bucket)
    settings = init_settings()


def format_cmd(ctx: typer.Context) -> str:
    return f"'{ctx.info_name} {ctx.invoked_subcommand}'"
