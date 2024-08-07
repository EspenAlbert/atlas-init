import logging
import os

import typer
from model_lib import parse_payload
from rich import prompt
from zero_3rdparty.file_utils import clean_dir

from atlas_init.cli_args import parse_key_values_any
from atlas_init.cli_cfn.aws import (
    activate_resource_type,
    create_stack,
    deactivate_third_party_type,
    deregister_cfn_resource_type,
    ensure_resource_type_activated,
    get_last_cfn_type,
    update_stack,
    wait_on_stack_ok,
)
from atlas_init.cli_cfn.aws import (
    delete_stack as delete_stack_aws,
)
from atlas_init.cli_cfn.cfn_parameter_finder import (
    check_execution_role,
    decode_parameters,
    dump_resource_to_file,
    infer_template_path,
    read_execution_role,
)
from atlas_init.cli_cfn.files import create_sample_file, has_md_link, iterate_schemas
from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.cloud.aws import run_in_regions
from atlas_init.repos.cfn import (
    CfnOperation,
    CfnType,
    Operation,
    infer_cfn_type_name,
    validate_type_name_regions,
)
from atlas_init.repos.path import Repo, current_dir, find_paths, resource_root
from atlas_init.settings.env_vars import active_suites, init_settings

app = typer.Typer(no_args_is_help=True)
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
    settings = init_settings()
    cfn_execution_role = read_execution_role(settings.load_env_vars_generated())
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
def example(
    type_name: str = typer.Argument(default_factory=infer_cfn_type_name),
    region: str = typer.Argument(...),
    stack_name: str = typer.Argument(...),
    operation: str = typer.Argument(...),
    resource_params: list[str] = typer.Option(..., "-r", default_factory=list),
    stack_timeout_s: int = typer.Option(300, "-t", "--stack-timeout-s"),
    delete_first: bool = typer.Option(False, help="Delete existing stack first"),
    force_deregister: bool = typer.Option(False),
    export_example_to_inputs: bool = typer.Option(False),
):
    resource_params_parsed = {}
    if resource_params:
        resource_params_parsed = parse_key_values_any(resource_params)
        if resource_params_parsed:
            logger.info(f"using resource params: {resource_params_parsed}")
    logger.info(
        f"about to update stack {stack_name} for {type_name} in {region} with {operation}, params: {resource_params_parsed}"
    )
    settings = init_settings()
    type_name, region = CfnType.validate_type_region(type_name, region)  # type: ignore
    CfnOperation(operaton=operation)  # type: ignore
    repo_path, resource_path, _ = find_paths(Repo.CFN)
    env_vars_generated = settings.load_env_vars_generated()
    cfn_execution_role = check_execution_role(repo_path, env_vars_generated)
    if not export_example_to_inputs:
        ensure_resource_type_activated(
            type_name,
            region,
            force_deregister,
            settings.is_interactive,
            resource_path,
            cfn_execution_role,
        )
    if operation == Operation.DELETE or delete_first:
        delete_stack_aws(region, stack_name)
        if not delete_first:
            return
    template_path = infer_template_path(repo_path, type_name, stack_name)
    template_path, parameters, not_found = decode_parameters(
        exported_env_vars=env_vars_generated,
        template_path=template_path,
        stack_name=stack_name,
        force_params=resource_params_parsed,
        resource_params=resource_params_parsed,
        type_name=type_name,
    )
    logger.info(f"parameters: {parameters}")
    if not_found:
        # TODO: support specifying these extra
        logger.critical(f"need to fill out parameters manually: {not_found} for {type_name}")
        raise typer.Exit(1)
    if not prompt.Confirm("parameters 👆looks good?")():
        raise typer.Exit(1)
    if export_example_to_inputs:
        out_inputs = dump_resource_to_file(resource_path / "inputs", template_path, type_name, parameters)
        logger.info(f"dumped to {out_inputs} ✅")
        return
    if operation == Operation.CREATE:
        create_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            role_arn=cfn_execution_role,
            parameters=parameters,
            timeout_seconds=stack_timeout_s,
        )
    elif operation == Operation.UPDATE:
        update_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            parameters=parameters,
            role_arn=cfn_execution_role,
            timeout_seconds=stack_timeout_s,
        )
    else:
        raise NotImplementedError


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
    env_extra = settings.load_env_vars_generated()
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
        cmd=[f"./{parent_dir}/{CREATE_FILENAME}", *context.args],
        env={**os.environ} | env_extra,
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
        resource_state = parse_payload(file)
        assert isinstance(resource_state, dict), f"input file with not a dict {resource_state}"
        samples_file = samples_dir / file.name
        if file.name.endswith("_create.json"):
            create_sample_file(samples_file, log_group_name, resource_state)
        if file.name.endswith("_update.json"):
            prev_state_path = file.parent / file.name.replace("_update.json", "_create.json")
            prev_state: dict = parse_payload(prev_state_path)  # type: ignore
            create_sample_file(
                samples_file,
                log_group_name,
                resource_state,
                prev_resource_state=prev_state,
            )
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
