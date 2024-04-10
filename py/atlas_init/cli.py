import logging
from typing import TypeVar
import typer
from shutil import copy
from model_lib import dump

from atlas_init.config import RepoAliastNotFound, TestSuit
from atlas_init.env_vars import (
    AtlasInitSettings,
    CwdIsNoRepoPathError,
)
from atlas_init.git_utils import owner_project_name
from atlas_init.go import run_go_tests
from atlas_init.rich_log import configure_logging
from atlas_init.tf_runner import TerraformRunError, get_tf_vars, run_terraform

logger = logging.getLogger(__name__)
app = typer.Typer(name="atlas_init", invoke_without_command=True, no_args_is_help=False)

T = TypeVar("T")
_extra_args: list[str] = []
settings: AtlasInitSettings = None # type: ignore


def tf_command(f: T) -> T:
    func_name: str = f.__name__ # type: ignore
    @app.command(name=func_name, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})
    def inner(ctx: typer.Context):
        app.command
        global settings
        _extra_args.extend(ctx.args)
        settings = _settings()
        return f() # type: ignore

    return inner # type: ignore

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, verbose: bool = typer.Option(False, help="use --verbose to get more output")):
    command = ctx.invoked_subcommand
    logger.info(f"in the app callback, verbose: {verbose}, command: {command}")
    if command is None:
        logger.warning("no command specified, will run 'init'")


@tf_command
def init():
    logger.info(f"in the init command: {_extra_args}")
    run_terraform(settings, "init", _extra_args)

@tf_command
def apply():
    logger.info(f"apply extra args: {_extra_args}")
    logger.info("in the apply command")
    try:
        suites = active_suites()
    except (CwdIsNoRepoPathError, RepoAliastNotFound) as e:
        logger.warning(repr(e))
        suites = []
    
    tf_vars = get_tf_vars(settings, suites)
    tf_vars_path = settings.tf_vars_path
    tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
    tf_vars_str = dump(tf_vars, "pretty_json")
    logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")
    tf_vars_path.write_text(tf_vars_str)

    try:
        run_terraform(settings, "apply", _extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))
        return
  
    if settings.env_vars_generated.exists():
        copy(settings.env_vars_generated, settings.env_vars_vs_code)
        logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")

@tf_command
def destroy():
    logger.info(f"destroy extra args: {_extra_args}, {settings}")


def _settings() -> AtlasInitSettings:
    return AtlasInitSettings.safe_settings()


def active_suites() -> list[TestSuit]:
    config = settings.config
    try:
        repo_path, rel_path = settings.repo_path_rel_path
    except CwdIsNoRepoPathError as e:
        raise e
    repo_url_path = owner_project_name(repo_path)
    repo_alias = config.repo_alias(repo_url_path)
    logger.info(
        f"repo_alias={repo_alias}, repo_path={repo_path}, repo_url_path={repo_url_path}"
    )
    change_paths = [rel_path]

    active_suites = config.active_test_suites(
        repo_alias, change_paths, settings.test_suites_parsed
    )
    logger.info(f"active_suites: {[s.name for s in active_suites]}")
    return active_suites

@app.command()
def test_go():
    suites = active_suites()
    sorted_suites = sorted(suite.name for suite in suites)
    logger.info(
        f"running go tests for {len(suites)} test-suites: {sorted_suites}"
    )
    # package_prefix = settings.config.go_package_prefix(repo_alias)
    # run_go_tests(repo_path, repo_alias, package_prefix, settings, active_suites)


def typer_main():
    configure_logging()
    app()


if __name__ == "__main__":
    typer_main()
