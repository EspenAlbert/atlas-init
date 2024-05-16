import logging
import os
import sys
from collections.abc import Callable
from functools import partial
from pydoc import locate

import typer
from zero_3rdparty.file_utils import iter_paths

from atlas_init import running_in_repo
from atlas_init.cli_cfn.app import app as app_cfn
from atlas_init.cli_helper import sdk_auto_changes
from atlas_init.cli_helper.go import run_go_tests
from atlas_init.cli_helper.run import (
    run_binary_command_is_ok,
    run_command_exit_on_failure,
)
from atlas_init.cli_helper.sdk import (
    SDK_VERSION_HELP,
    SdkVersion,
    SdkVersionUpgrade,
    find_breaking_changes,
    find_latest_sdk_version,
    format_breaking_changes,
    is_removed,
    parse_breaking_changes,
)
from atlas_init.cli_helper.tf_runner import (
    TerraformRunError,
    dump_tf_vars,
    export_outputs,
    get_tf_vars,
    run_terraform,
)
from atlas_init.cli_tf.app import app as app_tf
from atlas_init.repos.go_sdk import go_sdk_breaking_changes
from atlas_init.repos.path import (
    Repo,
    current_repo,
    current_repo_path,
    find_go_mod_dir,
    find_paths,
    resource_name,
)
from atlas_init.settings.config import RepoAliasNotFoundError
from atlas_init.settings.env_vars import (
    DEFAULT_PROFILE,
    AtlasInitSettings,
    active_suites,
    as_env_var_name,
    env_var_names,
    init_settings,
)
from atlas_init.settings.path import (
    CwdIsNoRepoPathError,
    dump_vscode_dotenv,
    repo_path_rel_path,
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
    hide_secrets(log_handler, {**os.environ})
    command = ctx.invoked_subcommand
    logger.info(f"in the app callback, log-level: {log_level}, command: {command}")


@app_command()
def init(context: typer.Context):
    settings = init_settings()
    extra_args = context.args
    logger.info(f"in the init command: {extra_args}")
    run_terraform(settings, "init", extra_args)


@app_command()
def apply(context: typer.Context, *, skip_outputs: bool = False):
    settings = init_settings()
    extra_args = context.args
    logger.info(f"apply extra args: {extra_args}")
    logger.info("in the apply command")
    try:
        suites = active_suites(settings)
    except (CwdIsNoRepoPathError, RepoAliasNotFoundError) as e:
        logger.warning(repr(e))
        suites = []

    tf_vars = get_tf_vars(settings, suites)
    dump_tf_vars(settings, tf_vars)

    try:
        run_terraform(settings, "apply", extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))  # noqa: TRY400
        raise typer.Exit(1) from e

    if not skip_outputs:
        export_outputs(settings)

    if settings.env_vars_generated.exists():
        dump_vscode_dotenv(settings.env_vars_generated, settings.env_vars_vs_code)
        logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")


@app_command()
def destroy(context: typer.Context):
    extra_args = context.args
    settings = init_settings()
    if not settings.tf_state_path.exists():
        logger.warning(f"no terraform state found  {settings.tf_state_path}, exiting")
        return
    tf_vars = get_tf_vars(settings, [])
    dump_tf_vars(settings, tf_vars)
    try:
        run_terraform(settings, "destroy", extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))  # noqa: TRY400
        return


@app_command()
def test_go():
    settings = init_settings()
    suites = active_suites(settings)
    sorted_suites = sorted(suite.name for suite in suites)
    logger.info(f"running go tests for {len(suites)} test-suites: {sorted_suites}")
    match repo_alias := current_repo():
        case Repo.CFN:
            raise NotImplementedError
        case Repo.TF:
            repo_path = current_repo_path()
            package_prefix = settings.config.go_package_prefix(repo_alias)
            run_go_tests(repo_path, repo_alias, package_prefix, settings, suites)
        case _:
            raise NotImplementedError


@app_command()
def sdk_upgrade(
    old: SdkVersion = typer.Argument(help=SDK_VERSION_HELP),
    new: SdkVersion = typer.Argument(
        default_factory=find_latest_sdk_version,
        help=SDK_VERSION_HELP + "\nNo Value=Latest",
    ),
    resource: str = typer.Option("", help="for only upgrading a single resource"),
    dry_run: bool = typer.Option(False, help="only log out the changes"),
    auto_change_name: str = typer.Option("", help="any extra replacements done in the file"),
):
    SdkVersionUpgrade(old=old, new=new)
    repo_path, _ = repo_path_rel_path()
    logger.info(f"bumping from {old} -> {new} @ {repo_path}")

    sdk_breaking_changes_path = go_sdk_breaking_changes(repo_path)
    all_breaking_changes = parse_breaking_changes(sdk_breaking_changes_path, old, new)
    replace_in = f"go.mongodb.org/atlas-sdk/{old}/admin"
    replace_out = f"go.mongodb.org/atlas-sdk/{new}/admin"
    auto_modifier: Callable[[str, str], str] | None = None
    if auto_change_name:
        func_path = f"{sdk_auto_changes.__name__}.{auto_change_name}"
        auto_modifier = locate(func_path)  # type: ignore

    change_count = 0
    resources: set[str] = set()
    resources_breaking_changes: set[str] = set()
    for path in iter_paths(repo_path, "*.go", ".mockery.yaml"):
        text_old = path.read_text()
        if replace_in not in text_old:
            continue
        r_name = resource_name(repo_path, path)
        if resource and resource != r_name:
            continue
        resources.add(r_name)
        logger.info(f"updating sdk version in {path}")
        if breaking_changes := find_breaking_changes(text_old, all_breaking_changes):
            changes_formatted = format_breaking_changes(text_old, breaking_changes)
            logger.warning(f"found breaking changes: {changes_formatted}")
            if is_removed(breaking_changes):
                resources_breaking_changes.add(r_name)
        text_new = text_old.replace(replace_in, replace_out)
        if not dry_run:
            if auto_modifier:
                text_new = auto_modifier(text_new, old)
            path.write_text(text_new)
        change_count += 1
    if change_count == 0:
        logger.warning("no changes found")
        return
    logger.info(f"changed in total: {change_count} files")
    resources_str = "\n".join(
        f"- {r} 💥" if r in resources_breaking_changes else f"- {r}" for r in sorted(resources) if r
    )
    logger.info(f"resources changed: \n{resources_str}")
    if dry_run:
        logger.warning("dry-run, no changes to go.mod")
        return
    go_mod_parent = find_go_mod_dir(repo_path)
    if not run_binary_command_is_ok("go", "mod tidy", cwd=go_mod_parent, logger=logger):
        logger.critical(f"failed to run go mod tidy in {go_mod_parent}")
        raise typer.Exit(1)


@app_command()
def pre_commit(
    skip_build: bool = typer.Option(default=False),
    skip_lint: bool = typer.Option(default=False),
):
    match current_repo():
        case Repo.CFN:
            repo_path, resource_path, r_name = find_paths()
            build_cmd = f"cd {resource_path} && make build"
            # TODO: understand why piping to grep doesn't work
            # f"golangci-lint run --path-prefix=./cfn-resources | grep {r_name}"
            format_cmd_str = "cd cfn-resources && golangci-lint run --path-prefix=./cfn-resources"
        case Repo.TF:
            repo_path = current_repo_path()
            build_cmd = "make build"
            format_cmd_str = "golangci-lint run"
        case _:
            raise NotImplementedError
    if skip_build:
        logger.warning("skipping build")
    else:
        run_command_exit_on_failure(build_cmd, cwd=repo_path, logger=logger)
    if skip_lint:
        logger.warning("skipping formatting")
    else:
        run_command_exit_on_failure(format_cmd_str, cwd=repo_path, logger=logger)


def typer_main():
    app()


if __name__ == "__main__":
    typer_main()
