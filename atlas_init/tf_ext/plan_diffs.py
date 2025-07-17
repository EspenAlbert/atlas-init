from functools import total_ordering
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from model_lib import Entity, dump, parse_model
from pydantic import Field, field_validator
from zero_3rdparty.file_utils import ensure_parents_write_text


PLAN_VARIABLES_FILENAME = "variables.tfvars.json"


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


def flatten_dict(d: dict[str, Any] | list[dict[str, Any]], current_address: str = "") -> dict[str, Any]:
    response_dict = {}
    if isinstance(d, list):
        for item in d:
            response_dict |= flatten_dict(item, current_address)
        return response_dict
    for key, value in d.items():
        if key == "resources":
            response_dict[current_address] = value
            continue
        if not isinstance(value, dict | list):
            continue
        response_dict |= flatten_dict(value, f"{current_address}.{key}".lstrip("."))
    return response_dict


class PlanOutput(Entity):
    planned_values: dict[str, list[PlannedResource]]
    format_version: str  # of the plan
    terraform_version: str  # used to generate the plan
    variables: dict[str, VariableUsage]
    configuration: dict[str, Any]
    relevant_attributes: dict[str, OutputUsage] | list[OutputUsage] = Field(default_factory=list)

    @field_validator("planned_values", mode="before")
    def unpack_planned_values(cls, v: dict[str, Any]):
        return flatten_dict(v)


def parse_plan_output(plan_json_path: Path) -> PlanOutput:
    return parse_model(plan_json_path, t=PlanOutput)


def resource_type_name_filename(resource_type: str, resource_name: str) -> str:
    return f"{resource_type}_{resource_name}.yaml"


def dump_plan_output_resources(output_dir: Path, plan_output: PlanOutput) -> list[Path]:
    output_files: dict[str, Path] = {}
    for resources in plan_output.planned_values.values():
        for resource in resources:
            resource_type_name = resource_type_name_filename(resource.type, resource.name)
            output_file = output_dir / resource_type_name
            assert resource_type_name not in output_files, f"Duplicate name {resource_type_name} in plan output"
            output_files[resource_type_name] = output_file
            ensure_parents_write_text(output_file, dump(resource.values, "yaml"))
    return list(output_files.values())


def dump_plan_output_variables(output_dir: Path, plan_output: PlanOutput) -> Path:
    variable_values = {name: value.value for name, value in plan_output.variables.items()}
    output_file = output_dir / PLAN_VARIABLES_FILENAME
    ensure_parents_write_text(output_file, dump(variable_values, "pretty_json"))
    return output_file


def read_variables_path(module_path: Path) -> Path:
    return module_path / PLAN_VARIABLES_FILENAME


class ResourceTypeName(Entity):
    type: str
    name: str


@total_ordering
class ResourceCheck(Entity):
    actual: ResourceTypeName
    expected_resource: ResourceTypeName

    def __lt__(self, other) -> bool:
        if not isinstance(other, ResourceCheck):
            raise TypeError
        return (self.actual.type, self.actual.name) < (other.actual.type, other.actual.name)

    def __str__(self) -> str:
        return f"Expecting Resource Match {self.expected_resource.type}.{self.expected_resource.name} == {self.actual.type}.{self.actual.name}"


class ExamplePlanCheck(Entity):
    resource_checks: list[ResourceCheck] = Field(default_factory=list)
    example_name: str
    expected_output_dir_name: str


def generate_expected_actual(
    stored_plan_outputs: Path, example_check: ExamplePlanCheck, plan_output: PlanOutput
) -> tuple[str, str]:
    expected_output_path = stored_plan_outputs / example_check.expected_output_dir_name
    assert expected_output_path.exists(), f"Expected output directory {expected_output_path} does not exist"
    expected_content, actual_content = [], []
    with TemporaryDirectory() as temp_dir:
        out_dir = Path(temp_dir)
        dump_plan_output_resources(out_dir, plan_output)
        for check in sorted(example_check.resource_checks):
            check_header = str(check)
            expected_file = expected_output_path / resource_type_name_filename(
                check.expected_resource.type, check.expected_resource.name
            )
            actual_file = out_dir / resource_type_name_filename(check.actual.type, check.actual.name)
            if not expected_file.exists():
                raise ValueError(f"Expected file {expected_file} doesn't exist!")
            if not actual_file.exists():
                raise ValueError(f"Actual file {actual_file} doesn't exist!")
            expected_content.append(f"\n{check_header}\n{expected_file.read_text()}")
            actual_content.append(f"\n{check_header}\n{actual_file.read_text()}")
    return "\n".join(expected_content), "\n".join(actual_content)
