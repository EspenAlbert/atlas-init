import logging
import os
import re
import sys
from functools import partial
from shutil import copy
from typing import Annotated, TypeAlias, TypeVar

from pydantic import AfterValidator
import typer
from model_lib import dump, parse_payload
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_args import SDK_VERSION_HELP, SdkVersion, SdkVersionUpgrade
from atlas_init.config import RepoAliasNotFound
from atlas_init.constants import GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS
from atlas_init.env_vars import (
    REPO_PATH,
    AtlasInitSettings,
    CwdIsNoRepoPathError,
    current_dir,
    active_suites
)
from atlas_init.git_utils import owner_project_name
from atlas_init.rich_log import configure_logging
from atlas_init.run import run_binary_command_is_ok, run_command_is_ok
from atlas_init.schema import (
    download_admin_api,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)
from atlas_init.schema_inspection import log_optional_only
from atlas_init.tf_runner import TerraformRunError, get_tf_vars, run_terraform

logger = logging.getLogger(__name__)
app = typer.Typer(name="atlas_init", invoke_without_command=True, no_args_is_help=True)

app_command = partial(app.command, context_settings={"allow_extra_args": True, "ignore_unknown_options": True})


def init_settings() -> AtlasInitSettings:
    return AtlasInitSettings.safe_settings()


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, help="use --verbose to get more output"),
):
    command = ctx.invoked_subcommand
    logger.info(f"in the app callback, verbose: {verbose}, command: {command}")

@app_command()
def init(context: typer.Context):
    settings = init_settings()
    extra_args = context.args
    logger.info(f"in the init command: {extra_args}")
    run_terraform(settings, "init", extra_args)


@app_command()
def apply(context: typer.Context):
    settings = init_settings()
    extra_args = context.args
    logger.info(f"apply extra args: {extra_args}")
    logger.info("in the apply command")
    try:
        suites = active_suites(settings)
    except (CwdIsNoRepoPathError, RepoAliasNotFound) as e:
        logger.warning(repr(e))
        suites = []

    tf_vars = get_tf_vars(settings, suites)
    tf_vars_path = settings.tf_vars_path
    tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
    tf_vars_str = dump(tf_vars, "pretty_json")
    logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")
    tf_vars_path.write_text(tf_vars_str)

    try:
        run_terraform(settings, "apply", extra_args)
    except TerraformRunError as e:
        logger.error(repr(e))
        return

    if settings.env_vars_generated.exists():
        copy(settings.env_vars_generated, settings.env_vars_vs_code)
        logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")


@app_command()
def destroy():
    raise NotImplementedError


@app_command()
def test_go():
    settings = init_settings()
    suites = active_suites(settings)
    sorted_suites = sorted(suite.name for suite in suites)
    logger.info(f"running go tests for {len(suites)} test-suites: {sorted_suites}")
    raise NotImplementedError("fix me later!")
    # package_prefix = settings.config.go_package_prefix(repo_alias)
    # run_go_tests(repo_path, repo_alias, package_prefix, settings, active_suites)


@app_command()
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

    if not run_binary_command_is_ok(
        cwd=SCHEMA_DIR,
        binary_name="tfplugingen-openapi",
        command=f"generate --config {generator_config_path.name} --output {provider_code_spec_path.name} {admin_api_path.name}",
        logger=logger,
    ):
        logger.critical("failed to generate spec")
        sys.exit(1)
    new_provider_spec = update_provider_code_spec(
        schema_parsed, provider_code_spec_path
    )
    provider_code_spec_path.write_text(new_provider_spec)
    logger.info(f"updated {provider_code_spec_path.name} ✅ ")

    go_code_output = SCHEMA_DIR / "internal"
    if go_code_output.exists():
        logger.warning(f"cleaning go code dir: {go_code_output}")
        clean_dir(go_code_output, recreate=True)

    if not run_binary_command_is_ok(
        cwd=SCHEMA_DIR,
        binary_name="tfplugingen-framework",
        command=f"generate resources --input ./{provider_code_spec_path.name} --output {go_code_output.name}",
        logger=logger,
    ):
        logger.critical("failed to generate plugin schema")
        sys.exit(1)

    logger.info(f"new files generated to {go_code_output} ✅")
    for go_file in sorted(go_code_output.rglob("*.go")):
        logger.info(f"new file @ '{go_file}'")


@app_command()
def cfn_inputs(skip_samples: bool = typer.Option(default=False)):
    settings = init_settings()
    suites = active_suites(settings)
    assert len(suites) == 1, "no test suit found"
    cwd = current_dir()
    suite = suites[0]
    assert suite.cwd_is_repo_go_pkg(cwd, repo_alias="cfn")
    env_extra = settings.load_env_vars_generated()
    if not run_command_is_ok(
        cwd=cwd,
        cmd=["./test/contract-testing/cfn-test-create-inputs.sh"],
        env={**os.environ} | env_extra,
        logger=logger,
    ):
        logger.critical("failed to create cfn contract input files")
        sys.exit(1)
    inputs_dir = cwd / "inputs"
    samples_dir = cwd / "samples"
    log_group_name = f"mongodb-atlas-{cwd.name}-logs"
    if not skip_samples:
        clean_dir(samples_dir)
    for file in sorted(inputs_dir.glob("*.json")):
        logger.info(f"input exist at inputs/{file.name} ✅")
        if skip_samples:
            continue
        if file.name.endswith("_create.json"):
            samples_file = samples_dir / file.name
            logger.info(f"adding sample @ {samples_file}")
            resource_state = parse_payload(file)
            assert isinstance(resource_state, dict)
            new_json = dump(
                {
                    "providerLogGroupName": log_group_name,
                    "previousResourceState": {},
                    "desiredResourceState": resource_state,
                },
                "json",
            )
            samples_file.write_text(new_json)


@app_command()
def schema_optional_only():
    settings = init_settings()
    repo_path, _ = settings.repo_path_rel_path
    assert owner_project_name(repo_path) == GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS
    log_optional_only(repo_path)





@app_command()
def sdk_upgrade(old: SdkVersion = typer.Argument(help=SDK_VERSION_HELP), new: SdkVersion = typer.Argument(help=SDK_VERSION_HELP)):
    settings = init_settings()
    SdkVersionUpgrade(old=old, new=new)
    repo_path, _ = settings.repo_path_rel_path
    logger.info(f"bumping from {old} -> {new} @ {repo_path}")

    replace_in = f"go.mongodb.org/atlas-sdk/{old}/admin"
    replace_out = f"go.mongodb.org/atlas-sdk/{new}/admin"

    change_count = 0
    for path in repo_path.rglob("*.go"):
        text_old = path.read_text()
        if replace_in not in text_old:
            continue
        logger.info(f"updating sdk version in {path}")
        text_new = text_old.replace(replace_in, replace_out)
        path.write_text(text_new)
        change_count += 1
    if change_count == 0:
        logger.warning("no changes found")
        return
    logger.info(f"changed in total: {change_count} files")
    go_mod_parent = None
    for go_mod in repo_path.rglob("go.mod"):
        if go_mod.parent == repo_path:
            go_mod_parent = go_mod.parent
            break
        elif go_mod.parent.parent == repo_path:
            go_mod_parent = go_mod.parent
            break
    else:
        raise ValueError("go.mod not found or more than 1 level deep")
    assert go_mod_parent
    if not run_binary_command_is_ok(
        "go", "mod tidy", cwd=go_mod_parent, logger=logger
    ):
        logger.critical(f"failed to run go mod tidy in {go_mod_parent}")
        raise typer.Exit(1)


def typer_main():
    configure_logging()
    app()


if __name__ == "__main__":
    typer_main()
