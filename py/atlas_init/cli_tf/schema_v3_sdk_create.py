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
    ComputedOptionalRequired,
    ListNestedAttribute,
    Resource,
    SingleNestedAttribute,
)
from atlas_init.cli_tf.schema_v3_sdk_base import (
    SDKAndSchemaAttribute,
    find_attribute,
    name_schema_struct,
    name_struct_attribute,
    schema_attributes,
)
from atlas_init.humps import pascalize

logger = logging.getLogger(__name__)


def generate_schema_to_model(resource: Resource, sdk_model: SDKModel) -> str:
    func_lines = tf_to_sdk_create_func(resource, sdk_model)
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


def tf_to_sdk_create_func(resource: Resource, sdk_model: SDKModel) -> list[str]:
    lines = [
        f"func NewAtlasReq({GoVarName.CTX} context.Context, {GoVarName.INPUT} *{TF_MODEL_NAME}, {GoVarName.DIAGS} *diag.Diagnostics) *admin.{sdk_model.name} {{"
        f"  return &admin.{sdk_model.name}{{"
    ]
    nested_attributes, call_lines = convert_or_call_lines(resource, sdk_model)
    lines.extend(call_lines)
    lines.extend(
        [
            "  }"  # end struct
            "}"  # end function
        ]
    )
    lines.extend(process_nested_attributes(nested_attributes))
    return lines


_tf_to_sdk_funcs = {
    ("string", "string"): lambda tf_ref: f"{tf_ref}.ValueString()",
    ("string", "*string"): lambda tf_ref: f"{tf_ref}.ValueStringPointer()",
    ("*string", "*string"): lambda tf_ref: f"{tf_ref}.ValueStringPointer()",
    (
        "*string",
        "*time.Time",
    ): lambda tf_ref: f"conversion.StringPtrToTimePtr({tf_ref}.ValueStringPointer())",
    ("*bool", "*bool"): lambda tf_ref: f"{tf_ref}.ValueBoolPointer()",
    (
        "int64",
        "*int",
    ): lambda tf_ref: f"conversion.Int64PtrToIntPtr({tf_ref}.ValueInt64Pointer())",
    (
        "*int64",
        "*int",
    ): lambda tf_ref: f"conversion.Int64PtrToIntPtr({tf_ref}.ValueInt64Pointer())",
    ("*float64", "*float64"): lambda tf_ref: f"{tf_ref}.ValueFloat64Pointer()",
    ("*int64", "*int64"): lambda tf_ref: f"{tf_ref}.ValueInt64Pointer()",
}


def tf_to_sdk_attribute_value(
    schema_attribute: Attribute,
    sdk_attribute: SDKAttribute,
    variable_name: GoVarName = GoVarName.INPUT,
) -> str:
    key = (schema_attribute.go_type_optional, sdk_attribute.go_type)
    if key in _tf_to_sdk_funcs:
        return _tf_to_sdk_funcs[key](f"{variable_name}.{pascalize(schema_attribute.name)}")
    raise ValueError(f"Could not find conversion function for {key} for attribute: {schema_attribute.name}")


def convert_or_call_lines(
    root: Resource | Attribute,
    sdk_model: SDKModel,
    variable_name: GoVarName = GoVarName.INPUT,
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    call_lines = []
    nested_attributes: list[SDKAndSchemaAttribute] = []
    tf_attributes = schema_attributes(root)
    for sdk_attr in sorted(sdk_model.attributes.values()):
        try:
            tf_attribute = find_attribute(tf_attributes, sdk_attr.tf_name, root.name)
        except ValueError as e:
            logger.warning(e)
            continue
        if tf_attribute.computed_optional_required == ComputedOptionalRequired.computed:
            continue
        if sdk_attr.is_nested:
            call_lines.append(
                f"  {sdk_attr.struct_name}: new{sdk_attr.struct_type_name}({GoVarName.CTX}, {variable_name}.{name_struct_attribute(tf_attribute.name)}, {GoVarName.DIAGS}),"
            )
            nested_attributes.append(SDKAndSchemaAttribute(sdk_attribute=sdk_attr, schema_attribute=tf_attribute))
        elif tf_attribute.is_required:
            call_lines.append(
                f"  {sdk_attr.struct_name}: {tf_to_sdk_attribute_value(tf_attribute, sdk_attr, variable_name)},"
            )
        else:
            call_lines.append(
                f"  {sdk_attr.struct_name}: conversion.NilForUnknown({variable_name}.{tf_attribute.name_pascal}, {tf_to_sdk_attribute_value(tf_attribute, sdk_attr, variable_name)}),"
            )
    return nested_attributes, call_lines


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
    sdk_model = sdk_attribute.as_sdk_model()
    lines: list[str] = [
        f"func new{sdk_model.name}(ctx context.Context, {GoVarName.INPUT} types.Object, diags *diag.Diagnostics) *admin.{sdk_model.name} {{",
        f"  var resp *admin.{sdk_model.name}",
        f"  if {GoVarName.INPUT}.IsUnknown() || {GoVarName.INPUT}.IsNull() {{",
        "    return resp",
        "  }",
        f"  {GoVarName.ITEM} := &{name_schema_struct(schema_attribute.name)}{{}}",
        f"  if localDiags := {GoVarName.INPUT}.As({GoVarName.CTX}, {GoVarName.ITEM}, basetypes.ObjectAsOptions{{}}); len(localDiags) > 0 {{",
        f"    {GoVarName.DIAGS}.Append(localDiags...)",
        "    return resp",
        "  }",
        f"  return &admin.{sdk_model.name}{{",
    ]
    nested_attributes, call_lines = convert_or_call_lines(schema_attribute, sdk_model, GoVarName.ITEM)
    lines.extend([*call_lines, "  }", "}"])  # end struct  # end function
    return nested_attributes, lines


@convert_nested_attribute.register
def _convert_list_nested_attriute(
    _: ListNestedAttribute,
    schema_attribute: Attribute,
    sdk_attribute: SDKAttribute,
) -> tuple[list[SDKAndSchemaAttribute], list[str]]:
    sdk_model = sdk_attribute.as_sdk_model()
    lines: list[str] = [
        f"func new{sdk_model.name}(ctx context.Context, {GoVarName.INPUT} types.List, diags *diag.Diagnostics) *[]admin.{sdk_model.name} {{",
        f"  if {GoVarName.INPUT}.IsUnknown() || {GoVarName.INPUT}.IsNull() {{",
        "    return nil",
        "  }",
        f"  {GoVarName.ELEMENTS} := make([]{name_schema_struct(schema_attribute.name)}, len({GoVarName.INPUT}.Elements()))",
        f"  if localDiags := {GoVarName.INPUT}.ElementsAs({GoVarName.CTX}, &{GoVarName.ELEMENTS}, false); len(localDiags) > 0 {{",
        f"    {GoVarName.DIAGS}.Append(localDiags...)",
        "    return nil",
        "  }",
        f"  {GoVarName.RESP} := make([]admin.{sdk_model.name}, len({GoVarName.INPUT}.Elements()))",
        f"  for i := range {GoVarName.ELEMENTS} {{",
        f"    {GoVarName.ITEM} := &{GoVarName.ELEMENTS}[i]",
        f"    resp[i] = admin.{sdk_model.name}{{",
    ]
    nested_attributes, call_lines = convert_or_call_lines(schema_attribute, sdk_model, GoVarName.ITEM)
    lines.extend(
        [
            *[f"    {line}" for line in call_lines],
            "    }",  # end struct
            "  }",  # end loop
            "  return &resp",
            "}",  # end function
        ]
    )
    return nested_attributes, lines
