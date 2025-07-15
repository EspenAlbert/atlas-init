from dataclasses import fields, is_dataclass
from typing import get_type_hints, get_origin, get_args, ClassVar, List, Set, Dict, Union

from atlas_init.tf_ext.gen_resource_main import format_tf_content
from atlas_init.tf_ext.models_module import ResourceAbs, ResourceTypePythonModule


def python_type_to_terraform_type(py_type) -> str:
    # Unwrap Optional/Union
    origin = get_origin(py_type)
    args = get_args(py_type)
    if origin is Union and type(None) in args:
        # Optional[X] or Union[X, None] -> X
        non_none = [a for a in args if a is not type(None)]
        if non_none:
            return python_type_to_terraform_type(non_none[0])
        else:
            return "any"
    if origin is list or origin is List:
        elem_type = python_type_to_terraform_type(args[0])
        return f"list({elem_type})"
    elif origin is set or origin is Set:
        elem_type = python_type_to_terraform_type(args[0])
        return f"set({elem_type})"
    elif origin is dict or origin is Dict:
        elem_type = python_type_to_terraform_type(args[1])
        return f"map({elem_type})"
    elif is_dataclass(py_type):
        return dataclass_to_object_type(py_type)
    elif py_type is str:
        return "string"
    elif py_type is int or py_type is float:
        return "number"
    elif py_type is bool:
        return "bool"
    else:
        return "any"


def dataclass_to_object_type(cls) -> str:
    lines = ["object({"]
    hints = get_type_hints(cls)
    for f in fields(cls):
        # Skip ClassVars and internal fields
        if (
            f.name.isupper()
            or (get_origin(f.type) is ClassVar)
            or f.name in getattr(cls, ResourceAbs.COMPUTED_ONLY_ATTRIBUTES_NAME, set())
        ):
            continue
        tf_type = python_type_to_terraform_type(hints[f.name])
        lines.append(f"  {f.name} = optional({tf_type})")
    lines.append("})")
    return "\n".join(lines)


def generate_module_variables(python_module: ResourceTypePythonModule) -> tuple[str, str]:
    base_resource = python_module.resource
    assert base_resource is not None, f"{python_module} does not have a resource"
    return generate_resource_variables(
        base_resource, base_resource.COMPUTED_ONLY_ATTRIBUTES
    ), generate_resource_variables(python_module.resource_ext, set(python_module.base_field_names))


def generate_resource_variables(resource: type[ResourceAbs] | None, ignored_names: set[str]) -> str:
    if resource is None:
        return ""
    out = []
    hints = get_type_hints(resource)
    for f in fields(resource):  # type: ignore
        if f.name.isupper() or f.name in ignored_names:
            continue
        tf_type = python_type_to_terraform_type(hints[f.name])
        out.append(f'''variable "{f.name}" {{
  type     = {tf_type}
  nullable = true
  default  = null
}}\n''')
    return format_tf_content("\n".join(out))
