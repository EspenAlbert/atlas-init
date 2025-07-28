from dataclasses import fields
from typing import Iterable
from atlas_init.tf_ext.models_module import ContainerType, ResourceTypePythonModule, ModuleGenConfig, ResourceAbs


def as_output(resource_type: str, field_name: str, output_name: str) -> str:
    return _as_output(output_name, f"{resource_type}.this.{field_name}")


def _as_output(name: str, value: str) -> str:
    return f"""\
output "{name}" {{
    value = {value}
}}
"""


def as_nested_output(
    resource_type: str,
    parent_cls: type[ResourceAbs],
    nested_types: dict[str, ContainerType[ResourceAbs]],
    config: ModuleGenConfig,
) -> Iterable[str]:
    resource_id = f"{resource_type}.this"
    for field_name, container_type in nested_types.items():
        if container_type.is_any:
            continue
        computed_nested_fields = [
            nested_field.name
            for nested_field in fields(container_type.type)
            if ResourceAbs.is_computed_only(nested_field.name, container_type.type)
        ]
        if container_type.is_list:
            for computed_field_name in computed_nested_fields:
                if container_type.is_optional and not ResourceAbs.is_required(field_name, parent_cls):
                    yield _as_output(
                        config.output_name(resource_type, field_name, computed_field_name),
                        f"{resource_id}.{field_name} == null ? null : {resource_id}.{field_name}.*.{computed_field_name}",
                    )
                else:
                    yield _as_output(
                        config.output_name(resource_type, field_name, computed_field_name),
                        f"{resource_id}.{field_name}.*.{computed_field_name}",
                    )
        elif container_type.is_dict or container_type.is_set:
            raise NotImplementedError("Dict and set container types not supported yet")
        else:
            for computed_field_name in computed_nested_fields:
                if container_type.is_optional and not ResourceAbs.is_required(field_name, parent_cls):
                    yield _as_output(
                        config.output_name(resource_type, field_name, computed_field_name),
                        f"{resource_id}.{field_name} == null ? null : {resource_id}.{field_name}.{computed_field_name}",
                    )
                else:
                    yield _as_output(
                        config.output_name(resource_type, field_name, computed_field_name),
                        f"{resource_id}.{field_name}.{computed_field_name}",
                    )


def generate_resource_output(py_module: ResourceTypePythonModule, config: ModuleGenConfig) -> str:
    nested_types = dict(py_module.nested_field_types)
    base_resource = py_module.resource
    assert base_resource is not None, f"Resource {py_module.resource_type} has no base resource"
    computed_field_names = [name for name in py_module.base_field_names_computed if name not in nested_types]
    return "\n".join(
        as_output(py_module.resource_type, field_name, config.output_name(py_module.resource_type, field_name))
        for field_name in computed_field_names
    ) + "\n".join(as_nested_output(py_module.resource_type, base_resource, nested_types, config))
