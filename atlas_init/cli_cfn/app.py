import logging
import os

import typer
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_cfn.aws import (
    activate_resource_type,
    deactivate_third_party_type,
    deregister_cfn_resource_type,
    get_last_cfn_type,
    wait_on_stack_ok,
)
from atlas_init.cli_cfn.aws import (
    delete_stack as delete_stack_aws,
)
from atlas_init.cli_cfn.contract import contract_test_cmd
from atlas_init.cli_cfn.example import example_cmd
from atlas_init.cli_cfn.files import (
    create_sample_file_from_input,
    has_md_link,
    iterate_schemas,
)
from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.cloud.aws import run_in_regions
from atlas_init.repos.cfn import (
    validate_type_name_regions,
)
from atlas_init.repos.path import Repo, current_dir, find_paths, resource_root
from atlas_init.settings.env_vars import active_suites, init_settings
from atlas_init.settings.env_vars_modules import TFModuleCfn

app = typer.Typer(no_args_is_help=True)
app.command(name="example")(example_cmd)
app.command(name="contract-test")(contract_test_cmd)
logger = logging.getLogger(__name__)


@app.command()
def reg(
    type_name: str,
    region_filter: str = typer.Option(default=""),
    dry_run: bool = typer.Option(False),
):
    if dry_run:
        logger.info("dry-run is set")
    type_name, regions = validate_type_name_regions(type_name, region_filter)
    assert len(regions) == 1, f"are you sure you want to activate {type_name} in all regions?"
    region = regions[0]
    found_third_party = deactivate_third_party_type(type_name, region, dry_run=dry_run)
    if not found_third_party:
        local = get_last_cfn_type(type_name, region, is_third_party=False)
        if local:
            deregister_cfn_resource_type(type_name, deregister=not dry_run, region_filter=region)
    logger.info(f"ready to activate {type_name}")
    init_settings(TFModuleCfn)
    cfn_execution_role = TFModuleCfn.from_env().CFN_EXAMPLE_EXECUTION_ROLE
    last_third_party = get_last_cfn_type(type_name, region, is_third_party=True)
    assert last_third_party, f"no 3rd party extension found for {type_name} in {region}"
    if dry_run:
        return
    activate_resource_type(last_third_party, region, cfn_execution_role)
    logger.info(f"{type_name} {last_third_party.version} is activated ✅")


@app.command()
def dereg(
    type_name: str,
    region_filter: str = typer.Option(default=""),
    dry_run: bool = typer.Option(False),
    is_local: bool = typer.Option(False),
):
    if dry_run:
        logger.info("dry-run is set")
    type_name, regions = validate_type_name_regions(type_name, region_filter)

    def deactivate(region: str):
        deactivate_third_party_type(type_name, region, dry_run=dry_run)

    def deactivate_local(region: str):
        deregister_cfn_resource_type(type_name, deregister=True, region_filter=region)

    if is_local:
        logger.info("deregistering local")
        run_in_regions(deactivate_local, regions)
    else:
        logger.info("deregistering 3rd party")
        run_in_regions(deactivate, regions)


@app.command()
def inputs(
    context: typer.Context,
    skip_samples: bool = typer.Option(default=False),
    single_input: int = typer.Option(0, "--input", "-i", help="keep only input_X files"),
):
    settings = init_settings()
    suites = active_suites(settings)
    assert len(suites) == 1, "no test suit found"
    cwd = current_dir()
    suite = suites[0]
    assert suite.cwd_is_repo_go_pkg(cwd, repo_alias="cfn")
    CREATE_FILENAME = "cfn-test-create-inputs.sh"  # noqa: N806
    create_dirs = ["test/contract-testing", "test"]
    parent_dir = None
    for parent in create_dirs:
        parent_candidate = cwd / parent / CREATE_FILENAME
        if parent_candidate.exists():
            parent_dir = parent
            break
    assert parent_dir, f"unable to find a {CREATE_FILENAME} in {create_dirs} in {cwd}"
    if not run_command_is_ok(
        cwd=cwd,
        cmd=f"./{parent_dir}/{CREATE_FILENAME}" + " ".join(context.args),
        env={**os.environ},
        logger=logger,
    ):
        logger.critical("failed to create cfn contract input files")
        raise typer.Exit(1)
    inputs_dir = cwd / "inputs"
    samples_dir = cwd / "samples"
    log_group_name = f"mongodb-atlas-{cwd.name}-logs"
    if not skip_samples and samples_dir.exists():
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
        create_sample_file_from_input(samples_dir, log_group_name, file)
    if single_input:
        for file in sorted(inputs_dir.glob("*.json")):
            new_name = file.name.replace(expected_input, "inputs_1")
            new_filename = inputs_dir / new_name
            file.rename(new_filename)
            logger.info(f"renamed from {file} -> {new_filename}")


@app.command()
def gen_docs():
    repo_path, *_ = find_paths(Repo.CFN)
    root = resource_root(repo_path)
    for path, schema in iterate_schemas(root):
        if has_md_link(schema.description):
            logger.warning(f"found md link in {schema.type_name} in {path}")


@app.command()
def wait_on_stack(
    stack_name: str = typer.Argument(...),
    region: str = typer.Argument(...),
    timeout_s: int = typer.Option(300, "-t", "--timeout-seconds"),
):
    wait_on_stack_ok(stack_name, region, timeout_seconds=timeout_s)
    logger.info(f"stack {stack_name} in {region} is ready ✅")


@app.command()
def delete_stack(
    stack_name: str = typer.Argument(...),
    region: str = typer.Argument(...),
):
    delete_stack_aws(region, stack_name)
    logger.info(f"stack {stack_name} in {region} is deleted ✅")
