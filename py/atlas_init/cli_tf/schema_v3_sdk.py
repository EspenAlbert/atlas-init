import logging
from functools import singledispatch
from queue import Queue
from typing import NamedTuple

from atlas_init.cli_tf.schema_v2 import (
    extend_import_urls,
    go_fmt,
    import_lines,
    package_name,
)
from atlas_init.cli_tf.schema_v2_sdk import GoVarName, SDKAttribute, SDKModel
from atlas_init.cli_tf.schema_v3 import (
    Attribute,
    ListNestedAttribute,
    Resource,
    SingleNestedAttribute,
)
from atlas_init.humps import camelize, pascalize

TF_MODEL_NAME = "TFModel"
logger = logging.getLogger(__name__)


def generate_model_go(resource: Resource, sdk_model: SDKModel) -> str:
    func_lines = sdk_to_tf_func(resource, sdk_model)
    import_urls = set()
    extend_import_urls(import_urls, func_lines)
    unformatted = "\n".join(
        [
            f"package {package_name(resource.name)}",
            "",
            *import_lines(import_urls),
            "",
            *func_lines,
        ]
    )
    return go_fmt(resource.name, unformatted)


def sdk_to_tf_func(resource: Resource, sdk_model: SDKModel) -> list[str]:
    lines = []
    lines.append(
        f"func New{TF_MODEL_NAME}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_model.name}) (*{TF_MODEL_NAME}, diag.Diagnostics) {{"
    )
    nested_attributes, call_lines = call_nested_functions(resource, sdk_model.list_nested_attributes())
    lines.extend(call_lines)
    # TODO: add timeouts attribute if it exists
    lines.extend(
        [
            f"  return &{TF_MODEL_NAME}{{",
            *tf_struct_create(resource, sdk_model),
            "  }, nil",  # close return
            "}\n",  # close function
        ]
    )
    lines.extend(process_nested_attributes(nested_attributes))
    return lines


@singledispatch
def schema_attributes(root: object) -> list[Attribute]:
    raise NotImplementedError(f"unsupported root type: {type(root)} to find schema attributes")


@schema_attributes.register
def _resource_attributes(root: Resource) -> list[Attribute]:
    return root.schema.attributes


@schema_attributes.register
def _attribute_nested(root: Attribute) -> list[Attribute]:
    return root.nested_attributes


def find_attribute(attributes: list[Attribute], name: str, root_name: str) -> Attribute:
    for schema_attribute in attributes:
        if name == schema_attribute.name:
            return schema_attribute
    raise ValueError(f"could not find schema attribute for {name} on resource: {root_name}")


def as_var_name(attr: SDKAttribute) -> str:
    return camelize(attr.json_name)


class SDKAndSchemaAttribute(NamedTuple):
    sdk_attribute: SDKAttribute
    schema_attribute: Attribute


def call_nested_functions(
    root: Resource | Attribute, nested_attributes: list[SDKAttribute]
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    lines = []
    schema_nested_attributes = schema_attributes(root)
    nested_generations = []
    for sdk_attribute in nested_attributes:
        schema_attribute = find_attribute(schema_nested_attributes, sdk_attribute.tf_name, root.name)
        var_name = as_var_name(sdk_attribute)
        lines.append(
            f"{var_name} := New{sdk_attribute.struct_name}(ctx, input.{sdk_attribute.struct_name}, {GoVarName.DIAGS})"
        )
        nested_generations.append(SDKAndSchemaAttribute(sdk_attribute, schema_attribute))
    if lines:
        lines.insert(0, "diags := &diag.Diagnostics{}")
        lines.extend(
            [
                "  if diags.HasError() {",
                "    return nil, *diags",
                "  }",
            ]
        )

    return nested_generations, lines


def tf_struct_create(
    root: Resource | Attribute,
    sdk_model: SDKModel,
    sdk_var_name: str = GoVarName.INPUT,
) -> list[str]:
    lines = []
    for attr in schema_attributes(root):
        if attr.is_nested:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(f"{camelize(attr.name)}: {as_var_name(local_var)},")
        elif attr.is_attribute:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(f"{camelize(attr.name)}: {sdk_var_name}.{local_var.struct_name},")
    return lines


def process_nested_attributes(
    nested_attributes: list[SDKAndSchemaAttribute],
) -> list[str]:
    lines = []
    queue = Queue()

    def add_nested_to_queue(attributes: list[SDKAndSchemaAttribute]):
        for nested in attributes:
            logger.info(f"found nested attribute: {nested.schema_attribute.name}")
            queue.put(nested)

    add_nested_to_queue(nested_attributes)
    while not queue.empty():
        sdk_attribute, schema_attribute = queue.get()
        more_nested_attributes, nested_lines = convert_nested_attribute(
            schema_attribute.nested_model, schema_attribute, sdk_attribute
        )
        lines.extend(nested_lines)
        add_nested_to_queue(more_nested_attributes)
    return lines


def _custom_object_type_name(name: str) -> str:
    return f"{pascalize(name)}ObjectType"


def _schema_struct_name(name: str) -> str:
    return f"TF{pascalize(name)}"


@singledispatch
def convert_nested_attribute(
    nested_model: object, schema_attribute: Attribute, _: SDKAttribute
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    raise NotImplementedError(f"unsupported nested attribute: {schema_attribute.name} of type {type(nested_model)}")


@convert_nested_attribute.register
def _convert_single_nested_attribute(
    _: SingleNestedAttribute,
    schema_attribute: Attribute,
    sdk_attribute: SDKAttribute,
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    object_type_name = _custom_object_type_name(schema_attribute.name)
    lines: list[str] = [
        f"func New{object_type_name}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.Object {{",
        f"  if {GoVarName.INPUT} == nil {{",
        f"    return types.ObjectNull({object_type_name}.AttrTypes)",
        "  }",
    ]

    nested_attributes, call_lines = call_nested_functions(schema_attribute, sdk_attribute.list_nested_attributes())
    lines.extend(call_lines)
    struct_name = _schema_struct_name(schema_attribute.name)
    lines.extend(
        [
            f"  tfModel := {struct_name}{{",
            *tf_struct_create(schema_attribute, sdk_attribute.as_sdk_model()),
            "  }",
            f"  objType, diagsLocal := types.ObjectValueFrom(ctx, {object_type_name}.AttrTypes, tfModel)",
            f"  {GoVarName.DIAGS}.Append(diagsLocal...)",
            "  return objType",
            "}\n",
        ]
    )
    return nested_attributes, lines


@convert_nested_attribute.register
def _convert_list_nested_attriute(
    _: ListNestedAttribute,
    schema_attribute: Attribute,
    sdk_attribute: SDKAttribute,
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    object_type_name = _custom_object_type_name(schema_attribute.name)
    lines: list[str] = [
        f"func New{object_type_name}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.List {{",
        f"  if {GoVarName.INPUT} == nil {{",
        f"    return types.ObjectNull({object_type_name}.AttrTypes)",
        "  }",
    ]
    struct_name = _schema_struct_name(schema_attribute.name)
    lines.extend(
        [
            f"  tfModels := make([]{struct_name}, len(*{GoVarName.INPUT}))",
            f"  for i, item := range *{GoVarName.INPUT} {{",
        ]
    )
    nested_attributes, call_lines = call_nested_functions(schema_attribute, sdk_attribute.list_nested_attributes())
    lines.extend([f"  {line}" for line in call_lines])
    lines.extend(
        [
            f"    tfModels[i] = {struct_name}{{",
            *tf_struct_create(
                schema_attribute,
                sdk_attribute.as_sdk_model(),
                sdk_var_name=GoVarName.ITEM,
            ),
            "    }",
            "  }",
            f"  listType, diagsLocal := types.ListValueFrom(ctx, {object_type_name}, tfModels)",
            f"  {GoVarName.DIAGS}.Append(diagsLocal...)",
            "  return listType",
            "}\n",
        ]
    )
    return nested_attributes, lines
