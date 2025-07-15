from abc import ABC
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import ClassVar
from dataclasses import dataclass, fields

from ask_shell import run_and_wait


@dataclass
class ResourceAbs(ABC):
    REQUIRED_ATTRIBUTES: ClassVar[set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[set[str]] = set()


def locals_def(resource_type: str, field_names: list[str]) -> str:
    variable_defs = "\n".join(f"        {name} = var.{name}" for name in field_names)
    return f"""
locals {{
    {resource_type}_fields = {{
{variable_defs}
    }}
}}
"""


def data_external(resource_type: str, field_names: list[str]) -> str:
    return f"""
data "external" "{resource_type}" {{
    program = ["python3", "${{path.module}}/{resource_type}.py"]
    query = {{
        input_json = jsonencode(local.{resource_type}_fields)
    }}
}}
"""


def resource_declare(
    resource_type: str, required_fields: set[str], nested_fields: set[str], field_names: list[str]
) -> str:
    # TODO: continue, use the ref of the data.external
    def output_field(field_name: str) -> str:
        return f"data.external.{resource_type}.result.{field_name}"

    def as_output_field(field_name: str) -> str:
        if field_name in nested_fields:
            if field_name in required_fields:
                return f"jsondecode({output_field(field_name)})"
            return f'{output_field(field_name)} == "" ? null : jsondecode({output_field(field_name)})'
        if field_name in required_fields:
            return output_field(field_name)
        return f'{output_field(field_name)} == "" ? null : {output_field(field_name)}'

    required = [f"    {field_name} = {as_output_field(field_name)}" for field_name in sorted(required_fields)]
    non_required = [
        f"    {field_name} = {as_output_field(field_name)}"
        for field_name in sorted(field_names)
        if field_name not in required_fields
    ]
    return f"""
resource "{resource_type}" "this" {{
    lifecycle {{
        precondition {{
            condition = length({output_field("error_message")}) == 0
            error_message = {output_field("error_message")}
        }}
    }}

{"\n".join(required)}
{"\n".join(non_required)}
}}
"""


def format_tf_content(content: str) -> str:
    with TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "content.tf"
        tmp_file.write_text(content)
        run_and_wait("terraform fmt .", cwd=tmp_dir)
        return tmp_file.read_text()


def generate_resource_main(resource_type: str, resource: type[ResourceAbs]) -> str:
    computed_only_fields = resource.COMPUTED_ONLY_ATTRIBUTES
    field_names = sorted(field.name for field in fields(resource) if field.name not in computed_only_fields)  # type: ignore
    return format_tf_content(
        "\n".join(
            line
            for line in [
                locals_def(resource_type=resource_type, field_names=field_names),
                data_external(resource_type=resource_type, field_names=field_names),
                "",
                resource_declare(
                    resource_type=resource_type,
                    required_fields=resource.REQUIRED_ATTRIBUTES,
                    nested_fields=resource.NESTED_ATTRIBUTES,
                    field_names=field_names,
                ),
                "",
            ]
        )
    )
