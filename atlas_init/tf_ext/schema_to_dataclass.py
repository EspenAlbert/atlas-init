from __future__ import annotations

import keyword
import logging
import re
from collections import defaultdict
from dataclasses import fields
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, ClassVar, Self

from ask_shell import ShellError, run_and_wait
from inflection import singularize
from model_lib import Entity
from pydantic import model_validator
from zero_3rdparty import humps
from zero_3rdparty.file_utils import copy, update_between_markers

from atlas_init.tf_ext.models_module import (
    ModuleGenConfig,
    ResourceAbs,
    ResourceTypePythonModule,
    import_resource_type_python_module,
)
from atlas_init.tf_ext.provider_schema import ResourceSchema, SchemaAttribute, SchemaBlock
from atlas_init.tf_ext.py_gen import (
    as_set,
    dataclass_matches,
    ensure_dataclass_use_conversion,
    import_from_path,
    longest_common_substring_among_all,
    make_post_init_line_optional,
    module_dataclasses,
    move_main_call_to_end,
    primitive_types,
)

logger = logging.getLogger(__name__)

MARKER_START = "# codegen atlas-init-marker-start"
MARKER_END = "# codegen atlas-init-marker-end"


def is_computed_only(attr: SchemaAttribute) -> bool:
    return bool(attr.computed) and not bool(attr.required) and not bool(attr.optional)


def type_from_schema_attr(attr: SchemaAttribute, parent_class_name=None, attr_name=None) -> str:
    # Only handle attribute types (not nested_type)
    t = attr.type
    if isinstance(t, str):
        return {
            "string": "str",
            "number": "float",
            "bool": "bool",
            "int": "int",
            "any": "Any",
        }.get(t, "Any")
    elif isinstance(t, list):
        # Terraform types: ["list", "string"] or ["set", "object", {...}]
        if t[0] in ("list", "set"):
            if len(t) == 2 and isinstance(t[1], str):
                return f"List[{type_from_schema_attr(SchemaAttribute(type=t[1]))}]"
            elif len(t) == 3 and isinstance(t[2], dict):
                # object type
                return "List[dict]"
        elif t[0] == "map":
            return "Dict[str, Any]"
    elif isinstance(t, dict):
        return "dict"
    return "Any"


def safe_name(name):
    return f"{name}_" if keyword.iskeyword(name) else name


def py_type_from_element_type(elem_type_val: str | dict[str, str] | Any) -> str:
    if isinstance(elem_type_val, str):
        return {
            "string": "str",
            "number": "float",
            "bool": "bool",
            "int": "int",
            "any": "Any",
        }.get(elem_type_val, "Any")
    elif isinstance(elem_type_val, dict):
        return "dict"
    else:
        return "Any"


class DcField(Entity):
    NO_DEFAULT: ClassVar[str] = "None"
    METADATA_DEFAULT_NAME: ClassVar[str] = "default_hcl"
    name: str
    type_annotation: str
    description: str | None = None
    default_value: str = NO_DEFAULT
    default_hcl_string: str | None = None
    nested_class_name: str = ""
    required: bool = False
    optional: bool = False
    computed: bool = False

    @model_validator(mode="after")
    def validate_self(self) -> Self:
        self.name = safe_name(self.name)
        return self

    @property
    def is_list(self) -> bool:
        return self.type_annotation.startswith("List[")

    @property
    def is_dict(self) -> bool:
        return self.type_annotation.startswith("Dict[")

    @property
    def is_nested(self) -> bool:
        return self.type_annotation.startswith(("List[", "Dict[", "Set[")) or self.nested_class_name != ""

    @property
    def metadata(self) -> dict:
        return {
            key: value
            for key, value in [
                ("description", self.description),
                (self.METADATA_DEFAULT_NAME, self.default_hcl_string),
            ]
            if value
        }

    @property
    def declare(self) -> str:
        if metadata := self.metadata:
            field_args = ["default=None", f"metadata={metadata}"]
            return f"    {self.name}: Optional[{self.type_annotation}] = field({', '.join(field_args)})"
        return f"    {self.name}: Optional[{self.type_annotation}] = None"

    @property
    def declare_required(self) -> str:
        """Why not use self.required? Even though an attribute is required in the schema, we might be able to infer the value, for example cluster_type"""
        if metadata := self.metadata:
            field_args = [f"metadata={metadata}"]
            return f"    {self.name}: {self.type_annotation} = field({', '.join(field_args)})"
        return f"    {self.name}: {self.type_annotation}"

    @property
    def post_init(self) -> str:
        if cls_name := self.nested_class_name:
            return make_post_init_line_optional(self.name, cls_name, is_list=self.is_list, is_map=self.is_dict)
        return ""

    @property
    def computed_only(self) -> bool:
        return self.computed and not self.required and not self.optional


def convert_to_dataclass(
    schema: ResourceSchema, existing: ResourceTypePythonModule, config: ModuleGenConfig, resource_type: str
) -> str:
    class_defs = []

    def block_to_class(block: SchemaBlock, class_name: str, extra_post_init: list[str] | None = None) -> str:
        lines = ["@dataclass", f"class {class_name}:"]
        dc_fields: list[DcField] = []

        def add_attribute(
            attr_name: str,
            attr: SchemaAttribute,
            type_annotation: str,
            *,
            required: bool = False,
            optional: bool = False,
            computed: bool = False,
            nested_class_name: str = "",
        ):
            dc_field = DcField(
                name=attr_name,
                type_annotation=type_annotation,
                required=required or bool(attr.required),
                optional=optional or bool(attr.optional),
                computed=computed or bool(attr.computed),
                description=attr.description,
                nested_class_name=nested_class_name,
            )
            dc_fields.append(dc_field)

        def add_block_attribute(
            attr_name: str,
            block_type: SchemaBlock,
            required: bool = False,
            optional: bool = False,
            computed: bool = False,
            description: str | None = None,
        ):
            nested_class_name = f"{class_name}_{attr_name.capitalize()}"
            type_annotation = (
                f"List[{nested_class_name}]" if block_type.nesting_mode in ("list", "set") else nested_class_name
            )
            dc_field = DcField(
                name=attr_name,
                type_annotation=type_annotation,
                required=required,
                optional=optional,
                computed=computed,
                description=description,
                nested_class_name=nested_class_name,
            )
            class_defs.append(block_to_class(block_type, nested_class_name))
            dc_fields.append(dc_field)

        for attr_name, attr in (block.attributes or {}).items():
            if attr.deprecated or attr.deprecated_message or attr_name in config.skip_variables_extra(resource_type):
                logger.info(f"skipping deprecated attribute {attr_name}")
                continue
            required = bool(attr.required)
            if nested_block := attr.nested_type:
                add_block_attribute(
                    attr_name,
                    nested_block,
                    required=required,
                    optional=bool(attr.optional),
                    computed=bool(attr.computed),
                    description=attr.description,
                )
                continue
            if elem_type_val := attr.element_type:
                elem_py_type = py_type_from_element_type(elem_type_val)
                match attr.type:
                    case ["map", *_]:
                        py_type = f"Dict[str, {elem_py_type}]"
                    case ["list", *_]:
                        py_type = f"List[{elem_py_type}]"
                    case ["set", *_]:
                        py_type = f"Set[{elem_py_type}]"
                    case _:
                        py_type = elem_py_type
                nested_class_name = ""
                if elem_py_type not in ("str", "float", "bool", "int", "Any", "dict"):
                    nested_class_name = elem_py_type
                add_attribute(attr_name, attr, py_type, nested_class_name=nested_class_name)
            else:
                py_type = type_from_schema_attr(attr, class_name, attr_name)
                add_attribute(attr_name, attr, py_type)

        for block_type_name, block_type in (block.block_types or {}).items():
            if block_type.deprecated or block_type_name in config.skip_variables_extra(resource_type):
                logger.info(f"skipping deprecated block type {block_type_name}")
                continue
            is_required = (block_type.min_items or 0) > 0 or bool(block_type.required)
            add_block_attribute(
                block_type_name,
                block_type.block,
                required=is_required,
                optional=bool(block_type.optional),
                description=block_type.description,
            )

        lines.append(
            f"    {ResourceAbs.NESTED_ATTRIBUTES_NAME}: ClassVar[Set[str]] = {as_set([dc_field.name for dc_field in dc_fields if dc_field.is_nested])}"
        )
        lines.append(
            f"    {ResourceAbs.REQUIRED_ATTRIBUTES_NAME}: ClassVar[Set[str]] = {as_set([dc_field.name for dc_field in dc_fields if dc_field.required])}"
        )
        lines.append(
            f"    {ResourceAbs.COMPUTED_ONLY_ATTRIBUTES_NAME}: ClassVar[Set[str]] = {as_set([dc_field.name for dc_field in dc_fields if dc_field.computed_only])}"
        )
        default_strings = {
            dc_field.name: default_hcl_string
            for dc_field in dc_fields
            if (default_hcl_string := config.attribute_default_hcl_strings.get(dc_field.name))
        }
        lines.append(f"    {ResourceAbs.DEFAULTS_HCL_STRINGS_NAME}: ClassVar[dict[str, str]] = {default_strings!r}")

        if not dc_fields:
            lines.append("    pass")
            return "\n".join(lines)
        if not config.use_descriptions:
            for dc_field in dc_fields:
                dc_field.description = None
        required_vars = config.required_variables(resource_type)
        lines.extend(dc_field.declare_required for dc_field in dc_fields if dc_field.name in required_vars)
        lines.extend(dc_field.declare for dc_field in dc_fields if dc_field.name not in required_vars)
        post_init_lines = [post_init for dc_field in dc_fields if (post_init := dc_field.post_init)]
        if extra_post_init:
            post_init_lines.extend(extra_post_init)
        if post_init_lines:
            lines.append("    def __post_init__(self):")
            lines.extend(post_init_lines)
        lines.extend(["", ""])
        return "\n".join(lines)

    root_class_name = "Resource"
    class_defs.append(block_to_class(schema.block, root_class_name, existing.extra_post_init_lines))

    import_lines = [
        "import json",
        "import sys",
        "from dataclasses import asdict, dataclass, field",
        "from typing import Optional, List, Dict, Any, Set, ClassVar, Union, Iterable",
    ]
    import_lines.extend(existing.extra_import_lines)

    module_str = "\n".join(import_lines + [""] + class_defs)
    return module_str.strip() + "\n"


_primitive_conversion = """
    
def format_primitive(value: Union[str, float, bool, int, None]):
    if value is None:
        return None
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value)
"""
_debug_logs = """
    from pathlib import Path
    logs_out = Path(__file__).parent / "logs.json"
    logs_out.write_text(json_str)
"""


def main_entrypoint(existing: ResourceTypePythonModule, config: ModuleGenConfig) -> str:
    parse_cls = "ResourceExt" if existing.resource_ext_cls_used else "Resource"
    errors_func_call = r'"\\n".join(errors(resource))' if existing.errors_func_used else '""'
    modify_out_func_call = "\n    resource = modify_out(resource)" if existing.modify_out_func_used else ""
    logs_debug = _debug_logs if config.debug_json_logs else ""
    return (
        _primitive_conversion
        + f"""
def main():
    input_data = sys.stdin.read()
    # Parse the input as JSON
    params = json.loads(input_data)
    input_json = params["input_json"]
    resource = {parse_cls}(**json.loads(input_json))
    error_message = {errors_func_call}
    primitive_types = ({", ".join(t.__name__ for t in primitive_types)}){modify_out_func_call}
    output = {{
        key: format_primitive(value) if value is None or isinstance(value, primitive_types) else json.dumps(value)
        for key, value in asdict(resource).items()
    }}
    output["error_message"] = error_message
    json_str = json.dumps(output){logs_debug}
    print(json_str)
if __name__ == "__main__":
    main()

"""
    )


def py_file_validate_and_auto_fixes(code: str, error_hint: str = "") -> str:
    with TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "dataclass.py"
        tmp_file.write_text(code)
        run_fmt_and_fixes(tmp_file)
        return tmp_file.read_text()


def run_fmt_and_fixes(file_path: Path, error_hint: str = ""):
    tmp_dir = file_path.parent
    try:
        run_and_wait("ruff format . --line-length 120", cwd=tmp_dir)
    except ShellError as e:
        logger.exception(f"Failed to format dataclass:\n{file_path.read_text()}\n{error_hint}")
        raise e
    try:
        run_and_wait("ruff check --fix .", cwd=tmp_dir)
    except ShellError as e:
        logger.exception(f"Failed to check dataclass:\n{file_path.read_text()}\n{error_hint}")
        raise e
    return file_path.read_text()


def simplify_classes(py_code: str) -> tuple[str, set[str]]:
    with TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "dataclass.py"
        tmp_file.write_text(py_code)
        module = import_from_path("dataclass", tmp_file)
        dataclasses = module_dataclasses(module)
        fields_to_dataclass = defaultdict(list)
        for name, dc in dataclasses.items():
            fields_to_dataclass[",".join(sorted(f.name for f in fields(dc)))].append(name)
        new_names: set[str] = set()

        def add_new_name(new_name: str) -> None:
            if new_name in new_names or new_name in dataclasses:
                raise ValueError(f"Duplicate new name: {new_name}")
            new_names.add(new_name)

        if duplicate_classes := {k: v for k, v in fields_to_dataclass.items() if len(v) > 1}:
            for duplicates in duplicate_classes.values():
                py_code, new_name = rename_and_remove_duplicates(duplicates, py_code)
                add_new_name(new_name)
        for old_classes in fields_to_dataclass.values():
            if len(old_classes) != 1:
                continue
            cls_name = old_classes[0]
            if "_" not in cls_name:
                continue
            new_name = extract_last_name_part(cls_name)
            py_code = _safe_replace(py_code, cls_name, new_name)
            add_new_name(new_name)
        return py_code, new_names


def _safe_replace(text: str, old: str, new: str) -> str:
    def replacer(match: re.Match) -> str:
        return match[0].replace(old, new)

    return re.sub(rf"\W({old})\W", replacer, text)


def extract_last_name_part(full_name: str) -> str:
    included_words = []
    for word in reversed(full_name.split("_")):
        included_words.insert(0, word)
        if word[0].isupper():
            break
    return singularize(humps.pascalize("_".join(included_words)))


def rename_and_remove_duplicates(duplicates: list[str], py_code: str) -> tuple[str, str]:
    duplicates_short = [extract_last_name_part(d) for d in duplicates]
    new_name = longest_common_substring_among_all(duplicates_short)
    for replace in duplicates:
        py_code = _safe_replace(py_code, replace, new_name)
    py_code = remove_duplicates(py_code, new_name)
    return py_code, new_name


def remove_duplicates(py_code: str, new_name) -> str:
    matches = list(dataclass_matches(py_code, new_name))
    logger.info(f"found {len(matches)} matches for {new_name}")
    while len(matches) > 1:
        next_match = matches.pop()
        py_code = py_code[: next_match.index_start] + py_code[next_match.index_end :]
    return py_code


SKIP_FILTER = {"Resource", "ResourceExt"}


def generate_python_from_schema(
    py_module: ResourceTypePythonModule, schema: ResourceSchema, config: ModuleGenConfig, resource_type: str
) -> str:
    dataclass_unformatted = convert_to_dataclass(schema, py_module, config, resource_type)
    dataclass_unformatted = simplify_classes(dataclass_unformatted)[0]
    return f"{dataclass_unformatted}\n{main_entrypoint(py_module, config)}"


def convert_and_format(
    resource_type: str,
    schema: ResourceSchema,
    config: ModuleGenConfig,
    existing_path: Path | None = None,
) -> str:
    if existing_path is not None and existing_path.exists():
        py_module = import_resource_type_python_module(resource_type, existing_path)
        with TemporaryDirectory() as tmp_path:
            tmp_file = Path(tmp_path) / f"{resource_type}.py"
            copy(existing_path, tmp_file)
            dataclass_unformatted = generate_python_from_schema(py_module, schema, config, resource_type)
            update_between_markers(tmp_file, dataclass_unformatted, MARKER_START, MARKER_END)
            move_main_call_to_end(tmp_file)
            ensure_dataclass_use_conversion(py_module.dataclasses, tmp_file, SKIP_FILTER)
            return run_fmt_and_fixes(tmp_file)
    existing = ResourceTypePythonModule(resource_type)
    dataclass_unformatted = generate_python_from_schema(existing, schema, config, resource_type)
    return py_file_validate_and_auto_fixes(f"{MARKER_START}\n{dataclass_unformatted}\n{MARKER_END}\n")
