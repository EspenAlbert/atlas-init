import keyword
from tempfile import TemporaryDirectory
from pathlib import Path
from types import ModuleType

from ask_shell import run_and_wait

from atlas_init.tf_ext.gen_resource_main import ResourceAbs
from atlas_init.tf_ext.provider_schema import ResourceSchema, SchemaAttribute, SchemaBlock


def as_set(values: list[str]) -> str:
    if not values:
        return "set()"
    return f"{{{', '.join(repr(v) for v in values)}}}"


def is_computed_only(attr: SchemaAttribute) -> bool:
    return bool(attr.computed) and not bool(attr.required) and not bool(attr.optional)


def convert_to_dataclass(schema: ResourceSchema) -> str:
    def safe_name(name):
        return name + "_" if keyword.iskeyword(name) else name

    class_defs = []

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

    def block_to_class(block: SchemaBlock, class_name: str) -> str:
        lines = ["@dataclass", f"class {class_name}:"]
        post_init_lines = []
        required_fields = []
        optional_fields = []
        nested_names = []
        required_attr_names = []

        for attr_name, attr in (block.attributes or {}).items():
            # If the attribute has a nested_type, generate a nested dataclass
            if attr.nested_type:
                nested_class_name = f"{class_name}_{attr_name.capitalize()}"
                nested_names.append(safe_name(attr_name))
                class_defs.append(block_to_class(attr.nested_type, nested_class_name))
                py_type = nested_class_name
            else:
                # Use element_type for lists/maps if available
                if isinstance(attr.type, list) and attr.type[0] in ("list", "set", "map") and attr.element_type:
                    elem_type_val = attr.element_type
                    if isinstance(elem_type_val, str):
                        elem_py_type = {
                            "string": "str",
                            "number": "float",
                            "bool": "bool",
                            "int": "int",
                            "any": "Any",
                        }.get(elem_type_val, "Any")
                    elif isinstance(elem_type_val, dict):
                        elem_py_type = "dict"
                    else:
                        elem_py_type = "Any"
                    if attr.type[0] == "map":
                        py_type = f"Dict[str, {elem_py_type}]"
                    else:
                        py_type = f"List[{elem_py_type}]"
                else:
                    py_type = type_from_schema_attr(attr, class_name, attr_name)
            # Compose field line
            field_line = f"    {safe_name(attr_name)}: Optional[{py_type}] = None"
            if attr.required:
                required_fields.append(field_line)
                required_attr_names.append(safe_name(attr_name))
            else:
                optional_fields.append(field_line)

        for block_type_name, block_type in (block.block_types or {}).items():
            nested_class_name = f"{class_name}_{block_type_name.capitalize()}"
            class_defs.append(block_to_class(block_type.block, nested_class_name))
            nested_names.append(safe_name(block_type_name))
            is_required = False
            if block_type.nesting_mode in ("list", "set"):
                is_required = (block_type.min_items or 0) > 0
                field_line = f"    {safe_name(block_type_name)}: Optional[List[{nested_class_name}]] = None"
                post_init_lines.append(
                    f"        if self.{block_type_name} is not None:\n"
                    f"            self.{block_type_name} = ["
                    f"x if isinstance(x, {nested_class_name}) else {nested_class_name}(**x) for x in self.{block_type_name}]"
                )
            else:
                is_required = bool(block_type.required)
                field_line = f"    {safe_name(block_type_name)}: Optional[{nested_class_name}] = None"
                post_init_lines.append(
                    f"        if self.{block_type_name} is not None and not isinstance(self.{block_type_name}, {nested_class_name}):\n"
                    f"            self.{block_type_name} = {nested_class_name}(**self.{block_type_name})"
                )
            (required_fields if is_required else optional_fields).append(field_line)

        # Add NESTED_ATTRIBUTES, REQUIRED_ATTRIBUTES, and COMPUTED_ONLY_ATTRIBUTES
        # A computed-only attribute is one where attr.computed is True and attr.required is not True
        computed_only_names = [
            safe_name(attr_name) for attr_name, attr in (block.attributes or {}).items() if is_computed_only(attr)
        ]
        lines.append(f"    NESTED_ATTRIBUTES: ClassVar[Set[str]] = {as_set(nested_names)}")
        lines.append(f"    REQUIRED_ATTRIBUTES: ClassVar[Set[str]] = {as_set(required_attr_names)}")
        lines.append(f"    COMPUTED_ONLY_ATTRIBUTES: ClassVar[Set[str]] = {as_set(computed_only_names)}")

        if not (required_fields or optional_fields):
            lines.append("    pass")
            return "\n".join(lines)
        lines.extend(required_fields)
        lines.extend(optional_fields)

        if post_init_lines:
            lines.append("    def __post_init__(self):")
            lines.extend(post_init_lines)
        lines.extend(["", ""])
        return "\n".join(lines)

    # Root class
    root_class_name = "Resource"
    class_defs.append(block_to_class(schema.block, root_class_name))

    # Generate necessary imports
    used_types = set()
    for class_def in class_defs:
        for line in class_def.splitlines():
            if ":" in line:
                field_type = line.split(":")[1].strip()
                if field_type.startswith("List[") or field_type.startswith("Optional["):
                    field_type = field_type.split("[")[1].split("]")[0]
                if field_type not in ["str", "float", "bool", "int", "Any", "dict"]:
                    used_types.add(field_type)

    import_lines = [
        "from dataclasses import dataclass",
        "from typing import Optional, List, Dict, Any, Set, ClassVar",
    ]
    if "Union" in used_types:
        import_lines.append("from typing import Union")
    if "Tuple" in used_types:
        import_lines.append("from typing import Tuple")

    module_str = "\n".join(import_lines + [""] + class_defs)
    return module_str.strip() + "\n"


def format_with_ruff(code: str) -> str:
    with TemporaryDirectory() as tmp_dir:
        tmp_file = Path(tmp_dir) / "dataclass.py"
        tmp_file.write_text(code)
        run_and_wait("ruff format . --line-length 120", cwd=tmp_dir)
        return tmp_file.read_text()


def import_from_path(module_name: str, file_path: Path) -> ModuleType:
    import importlib.util

    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def import_resource_type_dataclass(resource_type: str, generated_dataclass_path: Path) -> type[ResourceAbs]:
    module = import_from_path(resource_type, generated_dataclass_path)
    assert module
    resource = getattr(module, "Resource")
    assert resource
    return resource  # type: ignore


def convert_and_format(schema: ResourceSchema) -> str:
    dataclass_unformatted = convert_to_dataclass(schema)
    return format_with_ruff(dataclass_unformatted)
