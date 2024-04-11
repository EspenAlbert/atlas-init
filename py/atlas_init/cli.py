import logging
import os
from typing import TypeVar
import typer
from shutil import copy, which
from model_lib import dump
from zero_3rdparty.file_utils import clean_dir

from atlas_init.config import RepoAliastNotFound, TestSuit
from atlas_init.env_vars import (
    REPO_PATH,
    AtlasInitSettings,
    CwdIsNoRepoPathError,
)
from atlas_init.git_utils import owner_project_name
from atlas_init.go import run_go_tests
from atlas_init.rich_log import configure_logging
from atlas_init.schema import (
    download_admin_api,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)
from atlas_init.tf_runner import TerraformRunError, get_tf_vars, run_terraform
from atlas_init.util import run_command_is_ok

logger = logging.getLogger(__name__)
app = typer.Typer(name="atlas_init", invoke_without_command=True, no_args_is_help=False)

T = TypeVar("T")
_extra_args: list[str] = []
settings: AtlasInitSettings = None  # type: ignore


def tf_command(f: T) -> T:
    func_name: str = f.__name__  # type: ignore

    @app.command(
        name=func_name,
        context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
    )
    def inner(ctx: typer.Context):
        app.command
        global settings
        _extra_args.extend(ctx.args)
        settings = _settings()
        return f()  # type: ignore

    return inner  # type: ignore


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, help="use --verbose to get more output"),
):
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
    logger.info(f"running go tests for {len(suites)} test-suites: {sorted_suites}")
    raise NotImplementedError("fix me later!")
    # package_prefix = settings.config.go_package_prefix(repo_alias)
    # run_go_tests(repo_path, repo_alias, package_prefix, settings, active_suites)


@app.command()
def schema():
    SCHEMA_DIR = REPO_PATH / "schema"
    SCHEMA_DIR.mkdir(exist_ok=True)

    schema_parsed = parse_py_terraform_schema(REPO_PATH / "terraform.yaml")
    generator_config = dump_generator_config(schema_parsed)
    generator_config_path = SCHEMA_DIR / "generator_config.yaml"
    generator_config_path.write_text(generator_config)
    provider_code_spec_path = SCHEMA_DIR / "provider-code-spec.json"
    admin_api_path = SCHEMA_DIR / "admin_api.yaml"
    if admin_api_path.exists():
        logger.warning(f"using existing admin api @ {admin_api_path}")
    else:
        download_admin_api(admin_api_path)

    spec_gen_bin = which("tfplugingen-openapi")
    if not spec_gen_bin:
        logger.critical("please install 'tfplugingen-openapi'")
        return
    spec_ok = run_command_is_ok(
        [
            spec_gen_bin,
            *f"generate --config {generator_config_path.name} --output {provider_code_spec_path.name} {admin_api_path.name}".split(),
        ],
        env={**os.environ},
        cwd=SCHEMA_DIR,
        logger=logger,
    )
    if not spec_ok:
        logger.critical("failed to generate spec")
        return
    new_provider_spec = update_provider_code_spec(
        schema_parsed, provider_code_spec_path
    )
    provider_code_spec_path.write_text(new_provider_spec)
    logger.info(f"updated {provider_code_spec_path.name} ✅ ")

    plugin_gen_bin = which("tfplugingen-framework")
    if not plugin_gen_bin:
        logger.critical("please install 'tfplugingen-framework'")
        return
    go_code_output = SCHEMA_DIR / "internal"
    logger.warning(f"cleaning go code dir: {go_code_output}")
    clean_dir(go_code_output, recreate=True)

    plugin_gen_ok = run_command_is_ok(
        [
            plugin_gen_bin,
            *f"generate resources --input ./{provider_code_spec_path.name} --output {go_code_output.name}".split(),
        ],
        env={**os.environ},
        cwd=SCHEMA_DIR,
        logger=logger,
    )
    if not plugin_gen_ok:
        logger.critical("failed to generate plugin schema")
        return
    logger.info(f"new files generated to {go_code_output} ✅")
    for go_file in sorted(go_code_output.rglob("*.go")):
        logger.info(f"new file @ '{go_file}'")


def typer_main():
    configure_logging()
    app()


if __name__ == "__main__":
    typer_main()
