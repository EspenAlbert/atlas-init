from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path
from queue import Queue
from tempfile import TemporaryDirectory
from typing import Literal

from model_lib import Entity, copy_and_validate, parse_model
from pydantic import ConfigDict, Field, model_validator
from zero_3rdparty.enum_utils import StrEnum

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.humps import decamelize, pascalize

logger = logging.getLogger(__name__)
INDENT = "  "


class PlanModifier(StrEnum):
    use_state_for_unknown = "UseStateForUnknown"
    diff_suppress_json = "schemafunc.DiffSuppressJSON"


class SchemaAttributeValidator(StrEnum):
    string_is_json = "validate.StringIsJSON"


class SchemaAttribute(Entity):
    model_config = ConfigDict(
        frozen=False,
        validate_assignment=True,
        allow_population_by_field_name=True,
        extra="ignore",
    )  # type: ignore

    type: str = ""
    name: str = ""  # populated by the key of the attributes dict
    description: str = ""
    schema_ref: str = ""
    alias: str = ""  # comma separated list of aliases
    is_required: bool = False
    is_optional: bool = False
    is_computed: bool = False
    plan_modifiers: list[PlanModifier] = Field(default_factory=list)
    validators: list[SchemaAttributeValidator] = Field(default_factory=list)

    @property
    def tf_name(self) -> str:
        return decamelize(self.name)  # type: ignore

    @property
    def aliases(self) -> list[str]:
        return self.alias.split(",") if self.alias else []

    @property
    def is_nested(self) -> bool:
        return self.schema_ref != ""

    def merge(self, other: SchemaAttribute) -> SchemaAttribute:
        return SchemaAttribute(
            type=self.type or other.type,
            name=self.name or other.name,
            description=self.description or other.description,
            schema_ref=self.schema_ref or other.schema_ref,
            alias=self.alias or other.alias,
            is_required=self.is_required or other.is_required,
            is_optional=self.is_optional or other.is_optional,
            is_computed=self.is_computed or other.is_computed,
            plan_modifiers=self.plan_modifiers + other.plan_modifiers,
            validators=self.validators + other.validators,
        )

    def set_attribute_type(
        self,
        attr_type: Literal["required", "optional", "computed", "computed_optional"],
    ) -> None:
        match attr_type:
            case "required":
                self.is_required = True
                self.is_computed = False
                self.is_optional = False
            case "optional":
                self.is_optional = True
                self.is_computed = False
                self.is_required = False
            case "computed":
                self.is_computed = True
                self.is_required = False
                self.is_optional = False
            case "computed_optional":
                self.is_optional = True
                self.is_computed = True
                self.is_required = False
            case _:
                raise ValueError(f"Unknown attribute type {attr_type}")


class SkipAttribute(Exception):  # noqa: N818
    def __init__(self, attr_name: str):
        self.attr_name = attr_name
        super().__init__(f"Skipping attribute {attr_name}")


class NewAttribute(Exception):  # noqa: N818
    def __init__(self, attr_name: str):
        self.attr_name = attr_name
        super().__init__(f"New attribute {attr_name}")


def attr_path_matches(attr_path: str, path: str) -> bool:
    return fnmatch(attr_path, path)


class AttributeTypeModifiers(Entity):
    required: list[str] = Field(default_factory=list)
    optional: list[str] = Field(default_factory=list)
    computed: list[str] = Field(default_factory=list)
    computed_optional: set[str] = Field(default_factory=set)

    def set_attribute_type(self, attr: SchemaAttribute, parent_path: str = "") -> SchemaAttribute:
        attr_path = f"{parent_path}.{attr.tf_name}" if parent_path else attr.tf_name
        for attr_type, names in self.model_dump().items():
            for path_matcher in names:
                if attr_path_matches(attr_path, path_matcher):
                    logger.info(f"Setting attribute {attr_path} to {attr_type}")
                    attr.set_attribute_type(attr_type)  # type: ignore
                    return attr
        if attr.name in self.required:
            attr.is_required = True
            attr.is_computed = False
            attr.is_optional = False
        if attr.is_computed and attr.is_required:
            logger.warning(f"Attribute {attr.name} cannot be both computed and required, using required")
            attr.is_computed = False
        if attr.is_optional and attr.is_required:
            raise ValueError(f"Attribute {attr.name} cannot be both optional and required")
        if not attr.is_computed and not attr.is_required and not attr.is_optional:
            logger.warning(
                f"Attribute {attr.name} is neither read_only, required, nor optional, using computed-optional"
            )
            attr.is_optional = True
            attr.is_computed = True
        return attr


class SchemaResource(Entity):
    name: str = ""  # populated by the key of the resources dict
    description: str = ""
    attributes: dict[str, SchemaAttribute] = Field(default_factory=dict)
    attributes_skip: set[str] = Field(default_factory=set)
    paths: list[str] = Field(default_factory=list)
    attribute_type_modifiers: AttributeTypeModifiers = Field(default_factory=AttributeTypeModifiers)

    @model_validator(mode="after")
    def set_attribute_names(self):
        for name, attr in self.attributes.items():
            attr.name = name
        return self

    @property
    def nested_refs(self) -> set[str]:
        return {attr.schema_ref for attr in self.attributes.values() if attr.is_nested}

    def lookup_attribute(self, name: str) -> SchemaAttribute:
        if name in self.attributes_skip:
            raise SkipAttribute(name)
        if found := self.attributes.get(name):
            return found
        for attr in self.attributes.values():
            if name in attr.aliases:
                return attr
        raise NewAttribute(name)

    def sorted_attributes(self) -> list[SchemaAttribute]:
        return sorted(self.attributes.values(), key=lambda a: a.name)


class SchemaV2(Entity):
    attributes_skip: set[str] = Field(default_factory=set)
    resources: dict[str, SchemaResource] = Field(default_factory=dict)
    ref_resources: dict[str, SchemaResource] = Field(default_factory=dict)

    def ref_resource(self, ref: str, use_name: str = "") -> SchemaResource:
        if ref not in self.ref_resources:
            raise ValueError(f"Resource {ref} not found in ref_resources")
        resource = self.ref_resources[ref]
        return copy_and_validate(resource, name=use_name) if use_name else resource

    @model_validator(mode="after")
    def set_resource_names(self):
        for name, resource in self.resources.items():
            resource.name = name
        return self

    @model_validator(mode="after")
    def add_ignored_attributes(self):
        for resource in self.resources.values():
            resource.attributes_skip |= self.attributes_skip
        return self


def parse_schema(path: Path) -> SchemaV2:
    return parse_model(path, t=SchemaV2)


def generate_resource_go_resource_schema(schema: SchemaV2, resource_name: str) -> str:
    if resource_name not in schema.resources:
        raise ValueError(f"Resource {resource_name} not found in schema")
    resource = schema.resources[resource_name]
    return generate_go_resource_schema(schema, resource)


def generate_resource_go_schemas(schema: SchemaV2) -> Iterable[str]:
    for name, resource in schema.resources.items():
        logger.info(f"Generating Go schema for {name}")
        yield generate_go_resource_schema(schema, resource)


def package_name(resource_name: str) -> str:
    return resource_name.replace("_", "").lower()


def indent(level: int, line: str) -> str:
    return INDENT * level + line


_import_urls = [
    "context",
    "github.com/hashicorp/terraform-plugin-framework/attr",
    "github.com/hashicorp/terraform-plugin-framework/resource/schema",
    "github.com/hashicorp/terraform-plugin-framework/resource/schema/planmodifier",
    "github.com/hashicorp/terraform-plugin-framework/resource/schema/stringplanmodifier",
    "github.com/hashicorp/terraform-plugin-framework/schema/validator",
    "github.com/hashicorp/terraform-plugin-framework/types",
    "github.com/mongodb/terraform-provider-mongodbatlas/internal/common/schemafunc",
    "github.com/mongodb/terraform-provider-mongodbatlas/internal/common/validate",
]
_import_urls_dict = {url.split("/")[-1]: url for url in _import_urls}

package_usage_pattern = re.compile(r"(?P<package_name>[\w\d_]+)\.(?P<package_func>[\w\d_]+)")


def extend_import_urls(import_urls: set[str], code_lines: list[str]) -> None:
    for line in code_lines:
        for match in package_usage_pattern.finditer(line):
            package_name = match.group("package_name")
            if package_name in _import_urls_dict:
                import_urls.add(_import_urls_dict[package_name])
            else:
                err_msg = f"Unknown package '{package_name}' used in line {line}"
                raise ValueError(err_msg)


def import_lines(import_urls: set[str]) -> list[str]:
    stdlib_imports = {url for url in import_urls if "." not in url}
    pkg_imports = import_urls - stdlib_imports
    imports = sorted(stdlib_imports)
    if imports:
        imports.append("")
    imports.extend(sorted(pkg_imports))
    return [
        "import (",
        *[indent(1, f'"{url}"') if url else "" for url in imports],
        ")",
        "",
    ]


def generate_go_resource_schema(schema: SchemaV2, resource: SchemaResource) -> str:
    func_lines = resource_schema_func(schema, resource)
    object_type_lines = resource_object_type_lines(schema, resource)
    import_urls = set()
    extend_import_urls(import_urls, func_lines)
    extend_import_urls(import_urls, object_type_lines)
    unformatted = "\n".join(
        [
            f"package {package_name(resource.name)}",
            "",
            *import_lines(import_urls),
            "",
            *func_lines,
            "",
            *object_type_lines,
        ]
    )
    with TemporaryDirectory() as temp_dir:
        filename = f"{resource.name}.go"
        result_file = Path(temp_dir) / filename
        result_file.write_text(unformatted)
        if not run_binary_command_is_ok("go", f"fmt {filename}", cwd=Path(temp_dir), logger=logger):
            raise ValueError(f"Failed to format {result_file}")
        return result_file.read_text()


def resource_schema_func(schema: SchemaV2, resource: SchemaResource) -> list[str]:
    func_lines = [
        "func ResourceSchema(ctx context.Context) schema.Schema {",
        indent(1, "return schema.Schema{"),
        indent(2, "Attributes: map[string]schema.Attribute{"),
    ]
    for attr in resource.sorted_attributes():
        func_lines.extend(generate_go_attribute_schema_lines(schema, attr, 3, [resource]))
    func_lines.extend((indent(2, "},"), indent(1, "}"), "}"))
    return func_lines


_attr_schema_types = {
    "string": "schema.StringAttribute",
}


def attribute_header(attr: SchemaAttribute) -> str:
    if attr.is_nested:
        if attr.type != "object":
            raise NotImplementedError
        return "schema.SingleNestedAttribute"
    header = _attr_schema_types.get(attr.type)
    if header is None:
        raise NotImplementedError
    return header


def plan_modifier_call(modifier: PlanModifier, default_pkg_name: str) -> str:
    if "." in modifier:
        return f"{modifier}(),"
    return f"{default_pkg_name}.{pascalize(modifier)}(),"


def plan_modifiers_lines(attr: SchemaAttribute, line_indent: int) -> list[str]:
    # sourcery skip: reintroduce-else, swap-if-else-branches, use-named-expression
    plan_modifiers = attr.plan_modifiers
    if not plan_modifiers:
        return []
    modifier_package = {"string": "stringplanmodifier"}.get(attr.type)
    if not modifier_package:
        raise NotImplementedError
    modifier_header = {
        "string": "planmodifier.String",
    }.get(attr.type)
    if not modifier_header:
        raise NotImplementedError
    return [
        indent(line_indent, f"PlanModifiers: []{modifier_header}{{"),
        *[indent(line_indent + 1, plan_modifier_call(modifier, modifier_package)) for modifier in plan_modifiers],
        indent(line_indent, "},"),
    ]


def validate_call(validator: SchemaAttributeValidator) -> str:
    if "." not in validator:
        raise NotImplementedError
    return f"{validator}(),"


def validate_attribute_lines(attr: SchemaAttribute, line_indent: int) -> list[str]:
    # sourcery skip: reintroduce-else, swap-if-else-branches, use-named-expression
    if not attr.validators or attr.is_computed:
        return []
    validator_header = {
        "string": "validator.String",
    }.get(attr.type)
    if not validator_header:
        raise NotImplementedError
    return [
        indent(line_indent, f"Validators: []{validator_header}{{"),
        *[indent(line_indent + 1, validate_call(validator)) for validator in attr.validators],
        indent(line_indent, "},"),
    ]


def generate_go_attribute_schema_lines(
    schema: SchemaV2,
    attr: SchemaAttribute,
    line_indent: int,
    parent_resources: list[SchemaResource],
) -> list[str]:
    parent_path = ".".join(parent.name for parent in parent_resources[1:])
    parent_resources[0].attribute_type_modifiers.set_attribute_type(attr, parent_path)
    attr_name = attr.tf_name
    lines = [indent(line_indent, f'"{attr_name}": {attribute_header(attr)}{{')]
    if desc := attr.description or attr.is_nested and (desc := schema.ref_resource(attr.schema_ref).description):
        lines.append(indent(line_indent + 1, f'Description: "{desc.replace('\n', '\\n')}",'))
    if attr.is_required:
        lines.append(indent(line_indent + 1, "Required: true,"))
    if attr.is_optional:
        lines.append(indent(line_indent + 1, "Optional: true,"))
    if attr.is_computed:
        lines.append(indent(line_indent + 1, "Computed: true,"))
    if attr.validators:
        lines.extend(validate_attribute_lines(attr, line_indent + 1))
    if attr.plan_modifiers:
        lines.extend(plan_modifiers_lines(attr, line_indent + 1))
    if attr.is_nested:
        lines.append(indent(line_indent + 1, "Attributes: map[string]schema.Attribute{"))
        nested_attr = schema.ref_resource(attr.schema_ref, use_name=attr_name)
        for nes in nested_attr.attributes.values():
            lines.extend(
                generate_go_attribute_schema_lines(schema, nes, line_indent + 2, [*parent_resources, nested_attr])
            )
        lines.append(indent(line_indent + 1, "},"))
    lines.append(indent(line_indent, "},"))
    return lines


def struct_def(tf_name: str, resource_type: Literal["rs", "ds", "dsp", ""]) -> str:
    type_name = f"TF{pascalize(tf_name)}"
    suffix = {
        "rs": "RS",
        "ds": "DS",
        "dsp": "DS",
        "": "",
    }[resource_type]
    suffix += "Model"
    return f"type {type_name}{suffix} struct {{"


_tpf_types = {
    "string": "String",
    "int": "Int",
    "bool": "Bool",
    "map": "Map",
    "list": "List",
    "array": "List",
    "object": "Object",
}


def as_tpf_type(type_name: str) -> str:
    if tpf_type := _tpf_types.get(type_name):
        return tpf_type
    raise ValueError(f"Don't know how to convert {type_name} to TPF type")


def struct_field_line(attr: SchemaAttribute) -> str:
    tpf_type = as_tpf_type(attr.type)
    struct_field_name = pascalize(attr.tf_name).replace("Id", "ID").replace("Db", "DB")  # type: ignore
    return f'{struct_field_name} types.{tpf_type} `tfsdk:"{attr.tf_name}"`'


def as_object_type_name(attr: SchemaAttribute) -> str:
    tpf_type = as_tpf_type(attr.type)
    return f"{tpf_type}Type"


def custom_object_type_name(attr: SchemaAttribute) -> str:
    return f"{pascalize(attr.tf_name)}ObjectType"


def object_type_def(attr: SchemaAttribute) -> str:
    return f"var {custom_object_type_name(attr)} = types.ObjectType{{AttrTypes: map[string]attr.Type{{"


def object_type_field_line(attr: SchemaAttribute) -> str:
    if attr.is_nested:
        return f'"{attr.tf_name}": {custom_object_type_name(attr)},'
    object_type_name = as_object_type_name(attr)
    return f'"{attr.tf_name}": types.{object_type_name},'


def resource_object_type_lines(schema: SchemaV2, resource: SchemaResource) -> list[str]:
    nested_attributes = Queue()
    lines = [
        struct_def(resource.name, "rs"),
        *[indent(1, struct_field_line(attr)) for attr in resource.sorted_attributes()],
        "}",
        "",
    ]
    for attr in resource.sorted_attributes():
        if attr.is_nested:
            nested_attributes.put(attr)
    while not nested_attributes.empty():
        nested_attr = nested_attributes.get()
        nested_resource = schema.ref_resource(nested_attr.schema_ref, use_name=nested_attr.tf_name)
        logger.info("creating struct for nested attribute %s", nested_attr.name)
        lines.extend(
            [
                struct_def(nested_attr.tf_name, ""),
                *[indent(1, struct_field_line(attr)) for attr in nested_resource.sorted_attributes()],
                "}",
                "",
            ]
        )
        lines.extend(
            [
                object_type_def(nested_attr),
                *[indent(1, object_type_field_line(attr)) for attr in nested_resource.sorted_attributes()],
                "}}",
                "",
            ]
        )
        for attr in nested_resource.sorted_attributes():
            if attr.is_nested:
                nested_attributes.put(attr)
    return lines
