from queue import Queue
from typing import NamedTuple
from atlas_init.cli_tf.schema_v2_sdk import GoVarName, SDKAttribute, SDKModel
from atlas_init.cli_tf.schema_v3 import Attribute, Resource
from atlas_init.humps import camelize


TF_MODEL_NAME = "TFModel"


def generate_model_go(resource: Resource, sdk_model: SDKModel) -> str:
    func_lines = sdk_to_tf_func(resource, sdk_model)


def sdk_to_tf_func(resource: Resource, sdk_model: SDKModel) -> list[str]:
    lines = []
    lines.append(
        f"func New{TF_MODEL_NAME}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_model.name}) (*{TF_MODEL_NAME}, diag.Diagnostics) {{"
    )
    nested_attributes, call_lines = call_nested_functions(
        resource, sdk_model.list_nested_attributes()
    )
    lines.extend(call_lines)
    # todo: add timeouts attribute if it exists
    lines.extend([
        f"  return &{TF_MODEL_NAME}{{",
        *tf_struct_create(resource, sdk_model),
        "  }, nil", #close return
        "}\n", # close function
    ])
    lines.extend(process_nested_attributes(resource, nested_attributes))
    return lines



def find_schema_attribute(resource: Resource, sdk_attribute: SDKAttribute) -> Attribute:
    for schema_attribute in resource.schema.attributes:
        if sdk_attribute.json_name == schema_attribute.name:
            return schema_attribute
    raise ValueError(
        f"could not find schema attribute for {sdk_attribute.json_name} on resource: {resource.name}"
    )


def as_var_name(attr: SDKAttribute) -> str:
    return camelize(attr.json_name)

class SDKAndSchemaAttribute(NamedTuple):
    sdk_attribute: SDKAttribute
    schema_attribute: Attribute

def call_nested_functions(
    resource: Resource, nested_attributes: list[SDKAttribute]
) -> tuple[Queue[SDKAndSchemaAttribute], list[str]]:
    nested_queue: Queue[SDKAndSchemaAttribute] = Queue()
    lines = []
    for sdk_attribute in nested_attributes:
        schema_attribute = find_schema_attribute(resource, sdk_attribute)
        var_name = as_var_name(sdk_attribute)
        lines.append(
            f"{var_name} := New{sdk_attribute.struct_name}(ctx, input.{sdk_attribute.struct_name}, {GoVarName.DIAGS})"
        )
        nested_queue.put(SDKAndSchemaAttribute(sdk_attribute, schema_attribute))
    if lines:
        lines.insert(0, "diags := &diag.Diagnostics{}")
        lines.extend(
            [
                "  if diags.HasError() {",
                "    return nil, *diags",
                "  }",
            ]
        )

    return nested_queue, lines

def tf_struct_create(resource: Resource, sdk_model: SDKModel) -> list[str]:
    lines = []
    for attr in resource.schema.attributes:
        if attr.is_nested:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(f"{camelize(attr.name)}: {as_var_name(local_var)},")
        elif attr.is_attribute:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(f"{camelize(attr.name)}: input.{local_var.struct_name},")
    return lines

def process_nested_attributes(resource: Resource, nested_attributes: Queue[SDKAndSchemaAttribute]) -> list[str]:
    lines = []
    while not nested_attributes.empty():
        sdk_attribute, schema_attribute = nested_attributes.get()
        lines.extend(sdk_to_tf_func_nested(schema_attribute, sdk_attribute))
    return lines


_used_refs: set[str] = set()
def sdk_to_tf_func_nested(
    schema_attribute: Attribute, sdk_attribute: SDKAttribute
) -> list[str]:
    if schema_attribute.schema_ref in _used_refs:
        return []
    _used_refs.add(schema_attribute.schema_ref)
    is_object = schema_attribute.type == "object"
    if is_object:
        return sdk_to_tf_func_object(schema, schema_attribute, sdk_attribute)
    return sdk_to_tf_func_list(schema, schema_attribute, sdk_attribute)