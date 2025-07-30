import logging
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterable

from ask_shell import run_and_wait

from atlas_init.tf_ext.models_module import ModuleGenConfig, ResourceAbs, ResourceGenConfig
from atlas_init.tf_ext.schema_to_dataclass import ResourceTypePythonModule

logger = logging.getLogger(__name__)


def local_name_varsx(resource_type: str) -> str:
    return f"{resource_type}_varsx"


def local_name_vars(resource_type: str) -> str:
    return f"{resource_type}_vars"


def locals_def(module: ResourceTypePythonModule) -> str:
    base_defs = "\n".join(f"        {name} = var.{name}" for name in module.base_field_names_not_computed)
    if extras := module.extra_fields_names:
        extra_defs = "\n".join(f"        {name} = var.{name}" for name in extras)
        base_def = f"    {local_name_varsx(module.resource_type)} = {{\n{base_defs}\n    }}"
        extra_def = f"\n    {local_name_vars(module.resource_type)} = {{\n{extra_defs}\n    }}"
    else:
        base_def = f"    {local_name_vars(module.resource_type)} = {{\n{base_defs}\n    }}"
        extra_def = ""
    return f"""
locals {{
    {base_def}{extra_def}
}}
"""


def data_external(module: ResourceTypePythonModule, config: ModuleGenConfig) -> str:
    input_json_parts = [
        f"local.{local_name_vars(module.resource_type)}",
    ]
    if module.extra_fields_names:
        input_json_parts.append(f"local.{local_name_varsx(module.resource_type)}")
    if extras := config.inputs_json_hcl_extras:
        input_json_parts.extend(extras)
    inputs_json_merge = input_json_parts[0] if len(input_json_parts) == 1 else f"merge({', '.join(input_json_parts)})"
    return f"""
data "external" "{module.resource_type}" {{
    program = ["python3", "${{path.module}}/{module.resource_type}.py"]
    query = {{
        input_json = jsonencode({inputs_json_merge})
    }}
}}
"""


def resource_declare_direct(py_module: ResourceTypePythonModule, config: ResourceGenConfig) -> str:
    parent_cls = py_module.resource
    resource_type = py_module.resource_type
    assert parent_cls, f"{resource_type} does not have a resource"
    field_base = f"var.{resource_type}." if config.use_single_variable else "var."
    field_values = "\n".join(
        _field_value(parent_cls, name, field_base) for name in py_module.base_field_names_not_computed
    )

    return f"""
resource "{py_module.resource_type}" "this" {{
{field_values}
}}
"""


def _field_value(parent_cls: type[ResourceAbs], field_name: str, field_base: str = "var.") -> str:
    if ResourceAbs.is_computed_only(field_name, parent_cls):
        return ""
    this_indent = "  "
    if ResourceAbs.is_block(field_name, parent_cls):
        return "\n".join(f"{this_indent}{line}" for line in _handle_dynamic(parent_cls, field_name, field_base))
    return this_indent + f"{field_name} = {field_base}{field_name}"


def _handle_dynamic(
    parent_cls: type[ResourceAbs], dynamic_field_name: str, existing_ref: str = "var."
) -> Iterable[str]:
    try:
        container_type = next(
            t for name, t in ResourceTypePythonModule.container_types(parent_cls) if name == dynamic_field_name
        )
    except StopIteration:
        raise ValueError(f"Could not find container type for field {dynamic_field_name} in {parent_cls}")
    hcl_ref = f"{dynamic_field_name}.value."
    yield f'dynamic "{dynamic_field_name}" {{'
    ref = existing_ref + dynamic_field_name
    if container_type.is_list or container_type.is_set:
        if container_type.is_optional:
            yield f"  for_each = {ref} == null ? [] : {ref}"
        else:
            yield f"  for_each = {ref}"
    elif container_type.is_dict:
        raise NotImplementedError(f"Dict not supported for {dynamic_field_name} in {parent_cls}")
    else:  # singular
        if container_type.is_optional:
            yield f"  for_each = {ref} == null ? [] : [{ref}]"
        else:
            yield f"  for_each = [{ref}]"
    yield "  content {"
    yield from [f"    {line}" for line in _nested_fields(container_type.type, hcl_ref)]
    yield "  }"
    yield "}"


def _nested_fields(cls: type[ResourceAbs], hcl_ref: str) -> Iterable[str]:
    for field in fields(cls):
        field_name = field.name
        if ResourceAbs.is_computed_only(field_name, cls):
            continue
        if ResourceAbs.is_block(field_name, cls):
            yield from _handle_dynamic(cls, field_name, hcl_ref)
        else:
            yield _field_value(cls, field_name, hcl_ref)


def resource_declare(
    resource_type: str, required_fields: set[str], nested_fields: set[str], field_names: list[str]
) -> str:
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
        try:
            run_and_wait("terraform fmt .", cwd=tmp_dir)
        except Exception as e:
            logger.error(f"Failed to format tf content:\n{content}")
            raise e
        return tmp_file.read_text()


def generate_resource_main(python_module: ResourceTypePythonModule, config: ModuleGenConfig) -> str:
    resource = python_module.resource_ext or python_module.resource
    assert resource, f"{python_module} does not have a resource"
    resource_hcl = (
        resource_declare_direct(python_module, config.resource_config(python_module.resource_type))
        if config.skip_python
        else resource_declare(
            resource_type=python_module.resource_type,
            required_fields=resource.REQUIRED_ATTRIBUTES,
            nested_fields=resource.NESTED_ATTRIBUTES,
            field_names=python_module.base_field_names_not_computed,
        )
    )
    return format_tf_content(
        "\n".join(
            [
                *([] if config.skip_python else [locals_def(python_module)]),
                *([] if config.skip_python else [data_external(python_module, config)]),
                "",
                resource_hcl,
                "",
            ]
        )
    )
