import logging
from pathlib import Path
from typing import Any

import typer
from pydantic import field_validator, model_validator
from rich import prompt

from atlas_init.cli_args import parse_key_values_any
from atlas_init.cli_cfn.aws import (
    create_stack,
    ensure_resource_type_activated,
    update_stack,
)
from atlas_init.cli_cfn.aws import delete_stack as delete_stack_aws
from atlas_init.cli_cfn.cfn_parameter_finder import (
    check_execution_role,
    decode_parameters,
    dump_resource_to_file,
    dump_sample_file,
    infer_template_path,
)
from atlas_init.repos.cfn import CfnType, Operation, infer_cfn_type_name
from atlas_init.repos.path import Repo, find_paths
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings

logger = logging.getLogger(__name__)


class CfnExampleInputs(CfnType):
    stack_name: str
    operation: Operation
    example_name: str
    resource_params: dict[str, Any] | None = None
    stack_timeout_s: int
    delete_stack_first: bool
    force_deregister: bool
    force_keep: bool
    execution_role: str
    export_example_to_inputs: bool
    export_example_to_samples: bool

    @field_validator("resource_params", mode="before")
    @classmethod
    def validate_resource_params(cls, v):
        return parse_key_values_any(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def check(self):
        assert self.region_filter, "region is required"
        assert self.execution_role.startswith("arn:aws:iam::"), f"invalid execution role: {self.execution_role}"
        assert self.region
        return self

    @property
    def is_export(self) -> bool:
        return self.export_example_to_inputs or self.export_example_to_samples

    @property
    def region(self) -> str:
        region = self.region_filter
        assert isinstance(region, str), "region is required"
        return region


def example_cmd(
    type_name: str = typer.Option("", "-n", "--type-name", help="inferred from your cwd if not provided"),
    region: str = typer.Option("", help="inferred from your atlas_init cfn region if not provided"),
    stack_name: str = typer.Option(
        "",
        help="inferred from your atlas_init cfn profile name and example if not provided",
    ),
    operation: str = typer.Argument(...),
    example_name: str = typer.Option("", "-e", "--example-name", help="example filestem"),
    resource_params: list[str] = typer.Option(..., "-r", default_factory=list),
    stack_timeout_s: int = typer.Option(3600, "-t", "--stack-timeout-s"),
    delete_first: bool = typer.Option(False, "-d", "--delete-first", help="Delete existing stack first"),
    force_deregister: bool = typer.Option(False, "--dereg", help="Force deregister CFN Type"),
    force_keep: bool = typer.Option(False, "--noreg", help="Force keep CFN Type (do not prompt)"),
    execution_role: str = typer.Option("", "--execution-role", help="Execution role to use, otherwise inferred"),
    export_example_to_inputs: bool = typer.Option(
        False, "-o", "--export-example-to-inputs", help="Export example to inputs"
    ),
    export_example_to_samples: bool = typer.Option(
        False, "-s", "--export-example-to-samples", help="Export example to samples"
    ),
):
    settings = init_settings()
    assert settings.cfn_config, "no cfn config found, re-run atlas_init apply with CFN flags"
    repo_path, resource_path, _ = find_paths(Repo.CFN)
    env_vars_generated = settings.load_env_vars_generated()
    inputs = CfnExampleInputs(
        type_name=type_name or infer_cfn_type_name(),
        example_name=example_name,
        delete_stack_first=delete_first,
        region_filter=region or settings.cfn_region,
        stack_name=stack_name or f"{settings.cfn_profile}-{example_name or 'atlas-init'}",
        operation=operation,  # type: ignore
        resource_params=resource_params,  # type: ignore
        stack_timeout_s=stack_timeout_s,
        force_deregister=force_deregister,
        force_keep=force_keep,
        execution_role=execution_role or check_execution_role(repo_path, env_vars_generated),
        export_example_to_inputs=export_example_to_inputs,
        export_example_to_samples=export_example_to_samples,
    )
    example_handler(inputs, repo_path, resource_path, settings)


def example_handler(inputs: CfnExampleInputs, repo_path: Path, resource_path: Path, settings: AtlasInitSettings):
    logger.info(
        f"about to {inputs.operation} stack {inputs.stack_name} for {inputs.type_name} in {inputs.region_filter} params: {inputs.resource_params}"
    )
    type_name = inputs.type_name
    stack_name = inputs.stack_name
    env_vars_generated = settings.load_env_vars_generated()
    region = inputs.region
    operation = inputs.operation
    stack_timeout_s = inputs.stack_timeout_s
    delete_first = inputs.delete_stack_first
    force_deregister = inputs.force_deregister
    execution_role = inputs.execution_role
    logger.info(f"using execution role: {execution_role}")
    if not inputs.is_export and not inputs.force_keep:
        ensure_resource_type_activated(
            type_name,
            region,
            force_deregister,
            settings.is_interactive,
            resource_path,
            execution_role,
        )
    if not inputs.is_export and (operation == Operation.DELETE or delete_first):
        delete_stack_aws(region, stack_name, execution_role)
        if not delete_first:
            return
    template_path = infer_template_path(repo_path, type_name, stack_name, inputs.example_name)
    template_path, parameters, not_found = decode_parameters(
        exported_env_vars=env_vars_generated,
        template_path=template_path,
        stack_name=stack_name,
        force_params=inputs.resource_params,
        resource_params=inputs.resource_params,
        type_name=type_name,
    )
    logger.info(f"parameters: {parameters}")
    if not_found:
        # TODO: support specifying these extra
        logger.critical(f"need to fill out parameters manually: {not_found} for {type_name}")
        raise typer.Exit(1)
    if not prompt.Confirm("parameters 👆looks good?")():
        raise typer.Abort
    if inputs.export_example_to_inputs:
        out_inputs = dump_resource_to_file(resource_path / "inputs", template_path, type_name, parameters)
        logger.info(f"dumped to {out_inputs} ✅")
        return
    if inputs.export_example_to_samples:
        samples_dir = resource_path / "samples"
        samples_path = dump_sample_file(samples_dir, template_path, type_name, parameters)
        logger.info(f"dumped to {samples_path} ✅")
        return
    if operation == Operation.CREATE:
        create_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            role_arn=execution_role,
            parameters=parameters,
            timeout_seconds=stack_timeout_s,
        )
    elif operation == Operation.UPDATE:
        update_stack(
            stack_name,
            template_str=template_path.read_text(),
            region_name=region,
            parameters=parameters,
            role_arn=execution_role,
            timeout_seconds=stack_timeout_s,
        )
    else:
        raise NotImplementedError
