from pathlib import Path
from typing import Any

from model_lib import Entity, dump, parse_model
from pydantic import Field, field_validator
from zero_3rdparty.file_utils import ensure_parents_write_text


class PlannedResource(Entity):
    address: str
    mode: str
    type: str
    name: str
    provider_name: str
    schema_version: int
    values: dict[str, Any]
    sensitive_values: dict[str, Any]


class VariableUsage(Entity):
    value: Any


class OutputUsage(Entity):
    resource: str  # address to resource
    attribute: list[str]  # attribute name, only seen length 1 so far


def flatten_dict(d: dict[str, Any], current_address: str = "") -> dict[str, Any]:
    response_dict = {}
    for key, value in d.items():
        if key == "resources":
            response_dict[current_address] = value
            continue
        response_dict |= flatten_dict(value, f"{current_address}.{key}".lstrip("."))
    return response_dict


class PlanOutput(Entity):
    planned_values: dict[str, list[PlannedResource]]
    format_version: str  # of the plan
    terraform_version: str  # used to generate the plan
    variables: dict[str, VariableUsage]
    configuration: dict[str, Any]
    relevant_attributes: dict[str, OutputUsage] = Field(default_factory=dict)

    @field_validator("planned_values", mode="before")
    def unpack_planned_values(cls, v: dict[str, Any]):
        return flatten_dict(v)


def parse_resources_from_plan_json(plan_json_path: Path) -> PlanOutput:
    return parse_model(plan_json_path, t=PlanOutput)


def dump_plan_output_resources(output_dir: Path, plan_output: PlanOutput) -> list[Path]:
    output_files: dict[str, Path] = {}
    for resources in plan_output.planned_values.values():
        for resource in resources:
            resource_type_name = f"{resource.type}_{resource.name}"
            output_file = output_dir / f"{resource_type_name}.yaml"
            assert resource_type_name not in output_files, f"Duplicate name {resource_type_name} in plan output"
            output_files[resource_type_name] = output_file
            ensure_parents_write_text(output_file, dump(resource.values, "yaml"))
    return list(output_files.values())


def dump_plan_output_variables(output_dir: Path, plan_output: PlanOutput) -> Path:
    variable_values = {name: value.value for name, value in plan_output.variables.items()}
    output_file = output_dir / "variables.tfvars.json"
    ensure_parents_write_text(output_file, dump(variable_values, "pretty_json"))
    return output_file
