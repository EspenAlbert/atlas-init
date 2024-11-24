import logging
from functools import singledispatch
from queue import Queue

from atlas_init.cli_tf.schema_v2 import (
    extend_import_urls,
    go_fmt,
    import_lines,
    package_name,
)
from atlas_init.cli_tf.schema_v2_sdk import GoVarName, SDKAttribute, SDKModel
from atlas_init.cli_tf.schema_v3 import (
    TF_MODEL_NAME,
    Attribute,
    ListNestedAttribute,
    Resource,
    SingleNestedAttribute,
)
from atlas_init.cli_tf.schema_v3_sdk_base import (
    AllowedMissingAttributeError,
    SDKAndSchemaAttribute,
    find_attribute,
    name_schema_struct,
    name_struct_attribute,
    schema_attributes,
)
from atlas_init.humps import camelize, pascalize

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
    timeouts_signature = ", timeout timeouts.Value" if resource.use_timeout else ""
    lines.append(
        f"func New{TF_MODEL_NAME}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_model.name}{timeouts_signature}) (*{TF_MODEL_NAME}, diag.Diagnostics) {{"
    )
    nested_attributes, call_lines = call_nested_functions(resource, sdk_model.list_nested_attributes())
    lines.extend(call_lines)
    timeouts_set = ["    Timeouts: timeout,"] if resource.use_timeout else []
    lines.extend(
        [
            f"  return &{TF_MODEL_NAME}{{",
            *tf_struct_create(resource, sdk_model),
            *timeouts_set,
            "  }, nil",  # close return
            "}\n",  # close function
        ]
    )
    lines.extend(process_nested_attributes(nested_attributes))
    return lines


def as_var_name(attr: SDKAttribute) -> str:
    return camelize(attr.json_name)


def call_nested_functions(
    root: Resource | Attribute,
    nested_attributes: list[SDKAttribute],
    *,
    return_on_error: bool = True,
    sdk_var_name: GoVarName = GoVarName.INPUT,
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    lines = []
    schema_nested_attributes = schema_attributes(root)
    nested_generations = []
    for sdk_attribute in nested_attributes:
        try:
            schema_attribute = find_attribute(schema_nested_attributes, sdk_attribute.tf_name, root.name)
        except AllowedMissingAttributeError as e:
            logger.info(f"skipping {e!r}")
            continue
        var_name = as_var_name(sdk_attribute)
        lines.append(
            f"{var_name} := New{_name_custom_object_type(schema_attribute.name)}(ctx, {sdk_var_name}.{sdk_attribute.struct_name}, {GoVarName.DIAGS})"
        )
        nested_generations.append(SDKAndSchemaAttribute(sdk_attribute, schema_attribute))
    if lines and return_on_error:
        lines.insert(0, "diags := &diag.Diagnostics{}")
        lines.extend(
            [
                "  if diags.HasError() {",
                "    return nil, *diags",
                "  }",
            ]
        )

    return nested_generations, lines


_sdk_to_tf_funcs = {
    ("*string", "string"): lambda sdk_ref: f"types.StringPointerValue({sdk_ref})",
    ("string", "string"): lambda sdk_ref: f"types.StringValue({sdk_ref})",
    ("*int64", "int64"): lambda sdk_ref: f"types.Int64PointerValue({sdk_ref})",
    ("int64", "int64"): lambda sdk_ref: f"types.Int64Value({sdk_ref})",
    (
        "*int",
        "int64",
    ): lambda sdk_ref: f"types.Int64PointerValue(conversion.IntPtrToInt64Ptr({sdk_ref}))",
    ("*float64", "float64"): lambda sdk_ref: f"types.Float64PointerValue({sdk_ref})",
    ("float64", "float64"): lambda sdk_ref: f"types.Float64Value({sdk_ref})",
    ("*bool", "bool"): lambda sdk_ref: f"types.BoolPointerValue({sdk_ref})",
    ("bool", "bool"): lambda sdk_ref: f"types.BoolValue({sdk_ref})",
    (
        "*map[string]string",
        "map[string]string",
    ): lambda sdk_ref: f"conversion.ToTFMapOfString({GoVarName.CTX}, {GoVarName.DIAGS}, {sdk_ref})",
    (
        "map[string]string",
        "map[string]string",
    ): lambda sdk_ref: f"conversion.ToTFMapOfString({GoVarName.CTX}, {GoVarName.DIAGS}, &{sdk_ref})",
    (
        "*time.Time",
        "string",
    ): lambda sdk_ref: f"types.StringPointerValue(conversion.TimePtrToStringPtr({sdk_ref}))",
    (
        "time.Time",
        "string",
    ): lambda sdk_ref: f"types.StringValue(conversion.TimeToString({sdk_ref}))",
}


def sdk_to_tf_attribute_value(
    schema_attribute: Attribute,
    sdk_attribute: SDKAttribute,
    variable_name: GoVarName = GoVarName.INPUT,
) -> str:
    key = (sdk_attribute.go_type, schema_attribute.go_type)
    if key in _sdk_to_tf_funcs:
        return _sdk_to_tf_funcs[key](f"{variable_name}.{sdk_attribute.struct_name}")
    raise ValueError(f"Could not find conversion function for {key}")


# sdk_to_tf_attribute_value(schema_attribute, sdk_attribute, sdk_var_name)
def tf_struct_create(
    root: Resource | Attribute,
    sdk_model: SDKModel,
    sdk_var_name: GoVarName = GoVarName.INPUT,
) -> list[str]:
    lines = []
    for attr in schema_attributes(root):
        if attr.is_nested:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(f"{name_struct_attribute(attr.name)}: {as_var_name(local_var)},")
        elif attr.is_attribute:
            local_var = sdk_model.lookup_tf_name(attr.name)
            lines.append(
                f"{name_struct_attribute(attr.name)}: {sdk_to_tf_attribute_value(attr, local_var, sdk_var_name)},"
            )
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


def _name_custom_object_type(name: str) -> str:
    return f"{pascalize(name)}ObjType"


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
    object_type_name = _name_custom_object_type(schema_attribute.name)
    lines: list[str] = [
        f"func New{object_type_name}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.Object {{",
        f"  if {GoVarName.INPUT} == nil {{",
        f"    return types.ObjectNull({object_type_name}.AttrTypes)",
        "  }",
    ]

    nested_attributes, call_lines = call_nested_functions(
        schema_attribute, sdk_attribute.list_nested_attributes(), return_on_error=False
    )
    lines.extend(call_lines)
    struct_name = name_schema_struct(schema_attribute.name)
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
    object_type_name = _name_custom_object_type(schema_attribute.name)
    lines: list[str] = [
        f"func New{object_type_name}(ctx context.Context, {GoVarName.INPUT} *[]admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.List {{",
        f"  if {GoVarName.INPUT} == nil {{",
        f"    return types.ListNull({object_type_name})",
        "  }",
    ]
    struct_name = name_schema_struct(schema_attribute.name)
    lines.extend(
        [
            f"  tfModels := make([]{struct_name}, len(*{GoVarName.INPUT}))",
            f"  for i, item := range *{GoVarName.INPUT} {{",
        ]
    )
    nested_attributes, call_lines = call_nested_functions(
        schema_attribute,
        sdk_attribute.list_nested_attributes(),
        return_on_error=False,
        sdk_var_name=GoVarName.ITEM,
    )
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
