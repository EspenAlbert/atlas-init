from atlas_init.tf_ext.models_module import ResourceTypePythonModule, ModuleGenConfig


def as_output(resource_type: str, field_name: str, output_name: str) -> str:
    return f"""
output "{output_name}" {{
    value = {resource_type}.this.{field_name}
}}
"""


def generate_resource_output(py_module: ResourceTypePythonModule, config: ModuleGenConfig) -> str:
    computed_field_names = py_module.base_field_names_computed
    return "\n".join(
        as_output(py_module.resource_type, field_name, config.output_name(py_module.resource_type, field_name))
        for field_name in computed_field_names
    )
