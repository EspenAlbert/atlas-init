import logging
import os
from pydoc import locate
import sys
from functools import partial
from shutil import copy
from typing import Callable

import typer
from model_lib import dump, parse_payload
from zero_3rdparty.file_utils import clean_dir, iter_paths

from atlas_init.cfn import (
    create_stack,
    delete_role_stack,
    delete_stack,
    deregister_cfn_resource_type,
    get_last_cfn_type,
    update_stack,
)
from atlas_init.cfn_parameter_finder import (
    check_execution_role,
    decode_parameters,
    infer_template_path,
)
from atlas_init.cli_args import (
    SDK_VERSION_HELP,
    CfnOperation,
    CfnType,
    Operation,
    SdkVersion,
    SdkVersionUpgrade,
    parse_key_values,
)
from atlas_init.config import RepoAliasNotFound
from atlas_init.constants import (
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
    go_sdk_breaking_changes,
    resource_name,
)
from atlas_init.env_vars import (
    REPO_PATH,
    AtlasInitSettings,
    CwdIsNoRepoPathError,
    active_suites,
    current_dir,
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
from atlas_init.sdk import (
    find_breaking_changes,
    find_latest_sdk_version,
    format_breaking_changes,
    is_removed,
    parse_breaking_changes,
)
from atlas_init import sdk_auto_changes
from atlas_init.tf_runner import TerraformRunError, get_tf_vars, run_terraform

logger = logging.getLogger(__name__)
app = typer.Typer(name="atlas_init", invoke_without_command=True, no_args_is_help=True)

app_command = partial(
    app.command,
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)


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
def cfn_inputs(
    skip_samples: bool = typer.Option(default=False),
    single_input: int = typer.Option(
        0, "--input", "-i", help="keep only input_X files"
    ),
):
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
    expected_input = ""
    if single_input:
        logger.warning(f"will only use input_{single_input}")
        expected_input = f"inputs_{single_input}"
    for file in sorted(inputs_dir.glob("*.json")):
        if single_input and not file.name.startswith(expected_input):
            file.unlink()
            continue
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
    if single_input:
        for file in sorted(inputs_dir.glob("*.json")):
            new_name = file.name.replace(expected_input, "inputs_1")
            new_filename = inputs_dir / new_name
            file.rename(new_filename)
            logger.info(f"renamed from {file} -> {new_filename}")


@app_command()
def schema_optional_only():
    settings = init_settings()
    repo_path, _ = settings.repo_path_rel_path
    assert owner_project_name(repo_path) == GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS
    log_optional_only(repo_path)


@app_command()
def sdk_upgrade(
    old: SdkVersion = typer.Argument(help=SDK_VERSION_HELP),
    new: SdkVersion = typer.Argument(default_factory=find_latest_sdk_version, help=SDK_VERSION_HELP+"\nNo Value=Latest"),
    resource: str = typer.Option("", help="for only upgrading a single resource"),
    dry_run: bool = typer.Option(False, help="only log out the changes"),
    auto_change_name: str = typer.Option("", help="any extra replacements done in the file"),
):
    settings = init_settings()
    SdkVersionUpgrade(old=old, new=new)
    repo_path, _ = settings.repo_path_rel_path
    logger.info(f"bumping from {old} -> {new} @ {repo_path}")

    sdk_breaking_changes_path = go_sdk_breaking_changes(repo_path)
    all_breaking_changes = parse_breaking_changes(sdk_breaking_changes_path, old, new)
    replace_in = f"go.mongodb.org/atlas-sdk/{old}/admin"
    replace_out = f"go.mongodb.org/atlas-sdk/{new}/admin"
    auto_modifier: Callable[[str, str], str] | None = None 
    if auto_change_name:
        func_path = f"{sdk_auto_changes.__name__}.{auto_change_name}"
        auto_modifier = locate(func_path) # type: ignore

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
        f"- {r} 💥" if r in resources_breaking_changes else f"- {r}"
        for r in sorted(resources) if r
    )
    logger.info(f"resources changed: \n{resources_str}")
    if dry_run:
        logger.warning("dry-run, no changes to go.mod")
        return
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
    if not run_binary_command_is_ok("go", "mod tidy", cwd=go_mod_parent, logger=logger):
        logger.critical(f"failed to run go mod tidy in {go_mod_parent}")
        raise typer.Exit(1)


@app_command()
def cfn_dereg(type_name: str, region_filter: str):
    logger.info(f"about to deregister {type_name} in region {region_filter}")
    type_name, region_filter = CfnType.validate_type_region(type_name, region_filter)
    deregister_cfn_resource_type(
        type_name, deregister=True, region_filter=region_filter
    )
    delete_role_stack(type_name, region_filter)


@app_command()
def cfn_example(
    type_name: str,
    region: str,
    stack_name: str,
    operation: str,
    params: list[str] = typer.Option(default_factory=list),
):
    """
    2. check private registry (todo)
        1. submits to the private registry if not existing or --re-submit flag
    """
    params_parsed: dict[str, str] = {}
    if params:
        params_parsed = parse_key_values(params)
    logger.info(
        f"about to update stack {stack_name} for {type_name} in {region} with {operation}, params: {params}"
    )
    settings = init_settings()
    type_name, region = CfnType.validate_type_region(type_name, region)
    CfnOperation(operaton=operation)  # type: ignore
    repo_path, _ = settings.repo_path_rel_path
    assert (
        owner_project_name(repo_path) == GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES
    )
    env_vars_generated = settings.load_env_vars_generated()
    cfn_execution_role = check_execution_role(repo_path, env_vars_generated)

    cfn_type_details = get_last_cfn_type(type_name, region, is_third_party=False)
    logger.info(f"found cfn_type_details {cfn_type_details} for {type_name}")
    assert cfn_type_details, f"no cfn_type_details found for {type_name}"

    if operation == Operation.DELETE:
        delete_stack(region, stack_name)
        return
    template_path = infer_template_path(repo_path, type_name)
    parameters, not_found = decode_parameters(
        env_vars_generated, template_path, stack_name, params_parsed
    )
    if not_found:
        # todo: support specifying these extra
        logger.critical(f"need to fill out parameters manually: {not_found}")
        raise typer.Exit(1)
    if operation == Operation.CREATE:
        create_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            role_arn=cfn_execution_role,
            parameters=parameters,
        )
    elif operation == Operation.UPDATE:
        update_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            parameters=parameters,
            role_arn=cfn_execution_role,
        )
    else:
        raise NotImplementedError


def typer_main():
    configure_logging()
    app()


if __name__ == "__main__":
    typer_main()
