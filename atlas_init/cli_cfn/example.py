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
    CfnTemplate,
    dump_resource_to_file,
    dump_sample_file,
    infer_template_parameters,
    infer_template_path,
)
from atlas_init.repos.cfn import CfnType, Operation, infer_cfn_type_name
from atlas_init.repos.path import Repo, find_paths
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings
from atlas_init.settings.env_vars_generated import AWSSettings
from atlas_init.settings.env_vars_modules import TFModuleCfn

logger = logging.getLogger(__name__)


class CfnExampleInputs(CfnType):
    stack_name: str
    operation: Operation
    example_name: str
    resource_params: dict[str, Any] | None = None
    stack_timeout_s: int
    delete_stack_first: bool
    reg_version: str = ""
    force_deregister: bool
    force_keep: bool
    execution_role: str
    export_example_to_inputs: bool
    export_example_to_samples: bool
    register_all_types_in_example: bool

    @field_validator("resource_params", mode="before")
    @classmethod
    def validate_resource_params(cls, v):
        return parse_key_values_any(v) if isinstance(v, list) else v

    @model_validator(mode="after")
    def check(self):
        assert self.region_filter, "region is required"
        assert self.execution_role.startswith("arn:aws:iam::"), f"invalid execution role: {self.execution_role}"
        assert self.region
        if self.delete_stack_first and self.operation == Operation.UPDATE:
            err_msg = "cannot delete first when updating"
            raise ValueError(err_msg)
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
    resource_params: list[str] = typer.Option(
        ...,
        "-r",
        "--resource-param",
        default_factory=list,
        help="key=value, can be set many times",
    ),
    stack_timeout_s: int = typer.Option(3600, "-t", "--stack-timeout-s"),
    delete_first: bool = typer.Option(False, "-d", "--delete-first", help="Delete existing stack first"),
    reg_version: str = typer.Option("", "--reg-version", help="Register a specific version"),
    force_deregister: bool = typer.Option(False, "--dereg", help="Force deregister CFN Type"),
    force_keep: bool = typer.Option(False, "--noreg", help="Force keep CFN Type (do not prompt)"),
    execution_role: str = typer.Option("", "--execution-role", help="Execution role to use, otherwise inferred"),
    export_example_to_inputs: bool = typer.Option(
        False, "-o", "--export-example-to-inputs", help="Export example to inputs"
    ),
    export_example_to_samples: bool = typer.Option(
        False, "-s", "--export-example-to-samples", help="Export example to samples"
    ),
    register_all_types_in_example: bool = typer.Option(False, "--reg-all", help="Check all types"),
):
    settings = init_settings(TFModuleCfn, AWSSettings)
    cfn_settings = TFModuleCfn.from_env()
    aws_settings = AWSSettings.from_env()
    assert settings.tf_vars, "no cfn config found, re-run atlas_init apply with CFN flags"
    repo_path, resource_path, _ = find_paths(Repo.CFN)
    inputs = CfnExampleInputs(
        type_name=type_name or infer_cfn_type_name(),
        example_name=example_name,
        delete_stack_first=delete_first,
        region_filter=region or settings.cfn_region(aws_settings.AWS_REGION),
        stack_name=stack_name or f"{cfn_settings.MONGODB_ATLAS_PROFILE}-{example_name or 'atlas-init'}",
        operation=operation,  # type: ignore
        resource_params=resource_params,  # type: ignore
        stack_timeout_s=stack_timeout_s,
        force_deregister=force_deregister,
        reg_version=reg_version,
        force_keep=force_keep,
        execution_role=execution_role or cfn_settings.CFN_EXAMPLE_EXECUTION_ROLE,
        export_example_to_inputs=export_example_to_inputs,
        export_example_to_samples=export_example_to_samples,
        register_all_types_in_example=register_all_types_in_example,
    )
    example_handler(inputs, repo_path, resource_path, settings)


def example_handler(
    inputs: CfnExampleInputs,
    repo_path: Path,
    resource_path: Path,
    settings: AtlasInitSettings,
):
    logger.info(
        f"about to {inputs.operation} stack {inputs.stack_name} for {inputs.type_name} in {inputs.region_filter} params: {inputs.resource_params}"
    )
    type_name = inputs.type_name
    stack_name = inputs.stack_name
    region = inputs.region
    operation = inputs.operation
    stack_timeout_s = inputs.stack_timeout_s
    delete_first = inputs.delete_stack_first
    force_deregister = inputs.force_deregister
    execution_role = inputs.execution_role

    template_path = infer_template_path(repo_path, type_name, stack_name, inputs.example_name)
    parameters = infer_template_parameters(template_path, type_name, stack_name, inputs.resource_params or {})
    logger.info(f"parameters: {parameters}")
    if not prompt.Confirm("parameters 👆looks good?")():
        raise typer.Abort

    logger.info(f"using execution role: {execution_role}")
    if not inputs.is_export and not inputs.force_keep:
        ensure_resource_type_activated(
            type_name,
            region,
            force_deregister,
            settings.is_interactive,
            resource_path,
            execution_role,
            force_version=inputs.reg_version,
        )
    if not inputs.is_export and (operation == Operation.DELETE or delete_first):
        delete_stack_aws(region, stack_name, execution_role)
        if not delete_first:
            return
    if inputs.register_all_types_in_example:
        extra_example_types = [t for t in CfnTemplate.read_template_types(template_path) if t != type_name]
        for extra_type in extra_example_types:
            logger.info(f"extra type {extra_type} in example {template_path}")
            ensure_resource_type_activated(
                extra_type,
                region,
                force_deregister,
                settings.is_interactive,
                resource_path,
                execution_role,
            )
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
