from __future__ import annotations

import logging
import re
from functools import total_ordering
from pathlib import Path
from queue import Queue
from typing import NamedTuple

from model_lib import Entity
from pydantic import Field
from zero_3rdparty.enum_utils import StrEnum

from atlas_init.cli_tf.schema_v2 import (
    SchemaAttribute,
    SchemaResource,
    SchemaV2,
    add_go_variable_names,
    as_struct_name,
    custom_object_type_name,
    extend_import_urls,
    go_fmt,
    import_lines,
    package_name,
)
from atlas_init.humps import camelize, decamelize, pascalize

logger = logging.getLogger(__name__)


class GoStdlibType(StrEnum):
    STRING = "string"
    STRING_POINTER = "*string"
    TIME = "time.Time"
    TIME_POINTER = "*time.Time"
    BOOL = "bool"
    BOOL_POINTER = "*bool"
    INT = "int"
    INT_POINTER = "*int"
    INT64 = "int64"
    INT64_POINTER = "*int64"
    FLOAT64 = "float64"
    FLOAT64_POINTER = "*float64"
    MAP_STRING = "map[string]string"
    MAP_STRING_POINTER = "*map[string]string"


_go_types = set(GoStdlibType)


def is_go_type(value: str) -> bool:
    return value in _go_types


class GoVarName(StrEnum):
    INPUT = "input"
    ITEM = "item"
    DIAGS = "diags"
    CTX = "ctx"
    ELEMENTS = "elements"
    RESP = "resp"


add_go_variable_names(list(GoVarName))


_sdk_to_tf_funcs = {
    ("*string", "string"): lambda sdk_ref: f"types.StringPointerValue({sdk_ref})",
    ("string", "string"): lambda sdk_ref: f"types.StringValue({sdk_ref})",
    (
        "*time.Time",
        "string",
    ): lambda sdk_ref: f"types.StringPointerValue(conversion.TimePtrToStringPtr({sdk_ref}))",
}
# sdk_name -> tf_name
_sdk_attribute_aliases = {
    "group_id": "project_id",
    "mongo_dbemployee_access_grant": "mongo_db_employee_access_grant",
    "mongo_dbmajor_version": "mongo_db_major_version",
    "mongo_dbversion": "mongo_db_version",
}


@total_ordering
class SDKAttribute(Entity):
    go_type: GoStdlibType | str
    json_name: str
    struct_name: str
    nested_attributes: dict[str, SDKAttribute] = Field(default_factory=dict)

    @property
    def tf_name(self) -> str:
        default = decamelize(self.json_name)
        if override := _sdk_attribute_aliases.get(default):
            return override
        return default

    @property
    def is_nested(self) -> bool:
        return not is_go_type(self.go_type) or bool(self.nested_attributes)

    @property
    def struct_type_name(self) -> str:
        assert self.is_nested
        return self.go_type.removeprefix("*").removeprefix("[]")

    def list_nested_attributes(self) -> list[SDKAttribute]:
        return [attribute for attribute in sorted(self.nested_attributes.values()) if attribute.is_nested]

    def __lt__(self, other) -> bool:
        if not isinstance(other, SDKAttribute):
            raise TypeError
        return self.json_name < other.json_name

    def as_sdk_model(self) -> SDKModel:
        assert self.is_nested
        return SDKModel(
            name=self.struct_type_name,
            attributes=self.nested_attributes,
        )


SDKAttribute.model_rebuild()


class SDKModel(Entity):
    name: str
    attributes: dict[str, SDKAttribute] = Field(default_factory=dict)
    example_files: list[str] = Field(default_factory=list)

    def lookup_tf_name(self, tf_name: str) -> SDKAttribute:
        for attribute in self.attributes.values():
            if attribute.tf_name == tf_name:
                return attribute
        raise ValueError(f"Could not find SDK attribute for {self.name}.{tf_name}")

    def list_nested_attributes(self) -> list[SDKAttribute]:
        return [attribute for attribute in sorted(self.attributes.values()) if attribute.is_nested]


json_attribute_line = re.compile(
    r"^\s+(?P<struct_name>\w+)\s+(?P<go_type>[\w\*\.\[\]]+)\s+`json:\"(?P<json_name>\w+)",
    re.M,
)

_ignored_sdk_attributes = {"href", "links"}


def parse_sdk_model(repo_path: Path, model_name: str) -> SDKModel:
    model_path = repo_path / "admin" / f"model_{decamelize(model_name)}.go"
    model = SDKModel(name=model_name)
    for match in json_attribute_line.finditer(model_path.read_text()):
        struct_name = match.group("struct_name")
        go_type = match.group("go_type")
        json_name = match.group("json_name")
        if json_name in _ignored_sdk_attributes:
            continue
        sdk_attribute = model.attributes[struct_name] = SDKAttribute(
            go_type=go_type, json_name=json_name, struct_name=struct_name
        )
        if sdk_attribute.is_nested:
            nested_model = parse_sdk_model(repo_path, sdk_attribute.struct_type_name)
            sdk_attribute.nested_attributes = nested_model.attributes
    return model


def generate_model_go(schema: SchemaV2, resource: SchemaResource, sdk_model: SDKModel) -> str:
    func_lines = sdk_to_tf_func(schema, resource, sdk_model)
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


def find_schema_attribute(schema: SchemaV2, parent: SchemaResource, sdk_attribute: SDKAttribute) -> SchemaAttribute:
    err_msg = "we might need the schema to lookup sdk_attribute as an escape hatch"
    assert schema, err_msg
    return parent.lookup_tf_name(sdk_attribute.tf_name)


def find_sdk_attribute(schema_attribute: SchemaAttribute, sdk_model: SDKModel) -> SDKAttribute:
    return sdk_model.lookup_tf_name(schema_attribute.tf_name)


class SDKAndSchemaAttribute(NamedTuple):
    sdk_attribute: SDKAttribute
    schema_attribute: SchemaAttribute


def sdk_to_tf_attribute_value(
    schema_attribute: SchemaAttribute,
    sdk_attribute: SDKAttribute,
    variable_name: GoVarName = GoVarName.INPUT,
) -> str:
    key = (sdk_attribute.go_type, schema_attribute.type)
    if key in _sdk_to_tf_funcs:
        return _sdk_to_tf_funcs[key](f"{variable_name}.{sdk_attribute.struct_name}")
    raise ValueError(f"Could not find conversion function for {key}")


def sdk_to_tf_func(schema: SchemaV2, resource: SchemaResource, sdk_model: SDKModel) -> list[str]:
    struct_name = as_struct_name(resource.name, "")
    lines = [
        f"func New{struct_name}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_model.name}) (*{struct_name}, diag.Diagnostics) {{"
    ]
    nested_attributes, call_lines = call_nested_functions(schema, resource, sdk_model.list_nested_attributes())
    lines.extend(call_lines)

    lines.append(f"  return &{struct_name}{{")
    lines.extend(tf_struct_create(resource, sdk_model))
    lines.append("  }, nil")  # close return
    lines.append("}\n")  # close function

    lines.extend(process_nested_attributes(schema, nested_attributes))
    return lines


def process_nested_attributes(schema: SchemaV2, nested_attributes: Queue[SDKAndSchemaAttribute]) -> list[str]:
    lines = []
    while not nested_attributes.empty():
        sdk_attribute, schema_attribute = nested_attributes.get()
        lines.extend(sdk_to_tf_func_nested(schema, schema_attribute, sdk_attribute))
    return lines


def as_tf_struct_field_name(schema_attribute: SchemaAttribute) -> str:
    default = pascalize(schema_attribute.name)
    if default.endswith("Id"):
        return default[:-2] + "ID"
    return default


def tf_struct_create(
    resource: SchemaResource,
    sdk_model: SDKModel,
    sdk_var_name: GoVarName = GoVarName.INPUT,
) -> list[str]:
    lines = []
    for schema_attribute in resource.sorted_attributes():
        sdk_attribute = find_sdk_attribute(schema_attribute, sdk_model)
        tf_struct_field_name = as_tf_struct_field_name(schema_attribute)
        if sdk_attribute.is_nested:
            var_name = camelize(sdk_attribute.struct_name)
            lines.append(f"    {tf_struct_field_name}: {var_name},")
        else:
            lines.append(
                f"    {tf_struct_field_name}: {sdk_to_tf_attribute_value(schema_attribute, sdk_attribute, sdk_var_name)},"
            )
    return lines


def call_nested_functions(
    schema: SchemaV2, resource: SchemaResource, sdk_attributes: list[SDKAttribute]
) -> tuple[Queue[SDKAndSchemaAttribute], list[str]]:
    nested_attributes: Queue[SDKAndSchemaAttribute] = Queue()
    lines = []
    for sdk_attribute in sdk_attributes:
        schema_attribute = find_schema_attribute(schema, resource, sdk_attribute)
        var_name = camelize(sdk_attribute.struct_name)
        lines.append(
            f"  {var_name} := New{custom_object_type_name(schema_attribute)}(ctx, {GoVarName.INPUT}.{sdk_attribute.struct_name}, {GoVarName.DIAGS})"
        )
        nested_attributes.put(SDKAndSchemaAttribute(sdk_attribute, schema_attribute))
    if lines:
        lines.insert(0, "  diags := &diag.Diagnostics{}")
        lines.extend(
            [
                "  if diags.HasError() {",
                "    return nil, *diags",
                "  }",
            ]
        )
    return nested_attributes, lines


_used_refs: set[str] = set()


def sdk_to_tf_func_nested(
    schema: SchemaV2, schema_attribute: SchemaAttribute, sdk_attribute: SDKAttribute
) -> list[str]:
    if schema_attribute.schema_ref in _used_refs:
        return []
    _used_refs.add(schema_attribute.schema_ref)
    is_object = schema_attribute.type == "object"
    if is_object:
        return sdk_to_tf_func_object(schema, schema_attribute, sdk_attribute)
    return sdk_to_tf_func_list(schema, schema_attribute, sdk_attribute)


def sdk_to_tf_func_object(
    schema: SchemaV2, schema_attribute: SchemaAttribute, sdk_attribute: SDKAttribute
) -> list[str]:
    object_type_name = custom_object_type_name(schema_attribute)
    lines: list[str] = [
        f"func New{object_type_name}(ctx context.Context, {GoVarName.INPUT} *admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.Object {{",
        f"  var nilPointer *admin.{sdk_attribute.struct_type_name}",
        f"  if {GoVarName.INPUT} == nilPointer {{",
        f"    return types.ObjectNull({object_type_name}.AttrTypes)",
        "  }",
    ]
    resource = schema.ref_resource(schema_attribute.schema_ref, use_name=schema_attribute.schema_ref_name)
    nested_attributes, call_lines = call_nested_functions(schema, resource, sdk_attribute.list_nested_attributes())
    lines.extend(call_lines)
    struct_name = as_struct_name(resource.name, "")

    lines.extend(
        [
            f"  tfModel := {struct_name}{{",
            *tf_struct_create(resource, sdk_attribute.as_sdk_model()),
            "  }",
            f"  objType, diagsLocal := types.ObjectValueFrom(ctx, {object_type_name}.AttrTypes, tfModel)",
            f"  {GoVarName.DIAGS}.Append(diagsLocal...)",
            "  return objType",
            "}\n",
        ]
    )
    lines.extend(process_nested_attributes(schema, nested_attributes))
    return lines


def sdk_to_tf_func_list(schema: SchemaV2, schema_attribute: SchemaAttribute, sdk_attribute: SDKAttribute) -> list[str]:
    list_object_type = custom_object_type_name(schema_attribute)
    nested_resource = schema.ref_resource(schema_attribute.schema_ref, use_name=schema_attribute.schema_ref_name)
    lines: list[str] = [
        f"func New{list_object_type}(ctx context.Context, {GoVarName.INPUT} *[]admin.{sdk_attribute.struct_type_name}, diags *diag.Diagnostics) types.List {{",
        f"  var nilPointer *[]admin.{sdk_attribute.struct_type_name}",
        f"  if {GoVarName.INPUT} == nilPointer {{",
        f"    return types.ListNull({list_object_type})",
        "  }",
    ]
    struct_name = as_struct_name(nested_resource.name, "")
    if nested_list_attributes := [attr for attr in sdk_attribute.list_nested_attributes() if attr.is_nested]:
        logger.warning(f"Nested list attributes: {nested_list_attributes}, are not supported yet.")
    lines.extend(
        [
            f"  tfModels := make([]{struct_name}, len(*{GoVarName.INPUT}))",
            f"  for i, item := range *{GoVarName.INPUT} {{",
            f"    tfModels[i] = {struct_name}{{",
            *tf_struct_create(
                nested_resource,
                sdk_attribute.as_sdk_model(),
                sdk_var_name=GoVarName.ITEM,
            ),
            "    }",
            "  }",
            f"  listType, diagsLocal := types.ListValueFrom(ctx, {list_object_type}, tfModels)",
            f"  {GoVarName.DIAGS}.Append(diagsLocal...)",
            "  return listType",
            "}\n",
        ]
    )
    return lines
