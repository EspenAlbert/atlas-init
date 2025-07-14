import logging
import keyword
from tempfile import TemporaryDirectory
from pathlib import Path
from types import ModuleType
from typing import Any

from ask_shell import run_and_wait

from atlas_init.tf_ext.gen_resource_main import ResourceAbs
from atlas_init.tf_ext.provider_schema import ResourceSchema, SchemaAttribute, SchemaBlock

logger = logging.getLogger(__name__)


def as_set(values: list[str]) -> str:
    return f"{{{', '.join(repr(v) for v in values)}}}" if values else "set()"


def make_post_init_line(field_name: str, elem_type: str, is_map: bool = False, is_list: bool = False) -> str:
    if is_map:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = {{k: {elem_type}(**v) if not isinstance(v, {elem_type}) else v for k, v in self.{field_name}.items()}}"
        )
    elif is_list:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = [{elem_type}(**x) if not isinstance(x, {elem_type}) else x for x in self.{field_name}]"
        )
    else:
        return (
            f"        if self.{field_name} is not None and not isinstance(self.{field_name}, {elem_type}):\n"
            f"            self.{field_name} = {elem_type}(**self.{field_name})"
        )


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


def convert_to_dataclass(schema: ResourceSchema) -> str:
    class_defs = []

    def block_to_class(block: SchemaBlock, class_name: str) -> str:
        lines = ["@dataclass", f"class {class_name}:"]
        post_init_lines = []
        required_fields = []
        optional_fields = []
        nested_names = []
        required_attr_names = []

        def add_block_attribute(attr_name: str, block_type, is_list: bool = False, required: bool = False):
            nested_class_name = f"{class_name}_{attr_name.capitalize()}"
            nested_names.append(safe_name(attr_name))
            class_defs.append(block_to_class(block_type, nested_class_name))
            if is_list:
                field_line = f"    {safe_name(attr_name)}: Optional[List[{nested_class_name}]] = None"
                post_init_lines.append(make_post_init_line(attr_name, nested_class_name, is_map=False, is_list=True))
            else:
                field_line = f"    {safe_name(attr_name)}: Optional[{nested_class_name}] = None"
                post_init_lines.append(make_post_init_line(attr_name, nested_class_name, is_map=False, is_list=False))
            (required_fields if required else optional_fields).append(field_line)
            if required:
                required_attr_names.append(safe_name(attr_name))

        for attr_name, attr in (block.attributes or {}).items():
            # If the attribute has a nested_type, generate a nested dataclass
            if nested_block := attr.nested_type:
                is_list = nested_block.nesting_mode in ("list", "set")
                add_block_attribute(attr_name, nested_block, is_list=is_list, required=bool(attr.required))
            else:
                is_collection_attribute = (
                    isinstance(attr.type, list) and len(attr.type) > 0 and attr.type[0] in ("list", "set", "map")
                )
                if is_collection_attribute:
                    nested_names.append(safe_name(attr_name))
                if is_collection_attribute and attr.element_type:
                    elem_type_val = attr.element_type
                    elem_py_type = py_type_from_element_type(elem_type_val)
                    if isinstance(attr.type, list) and attr.type[0] == "map":
                        py_type = f"Dict[str, {elem_py_type}]"
                    else:
                        py_type = f"List[{elem_py_type}]"
                    # Add post-init for non-primitive element types (i.e., nested dataclasses)
                    # Only add if elem_py_type is a class generated in this module (not a builtin)
                    if elem_py_type not in ("str", "float", "bool", "int", "Any", "dict"):
                        is_map = isinstance(attr.type, list) and attr.type[0] == "map"
                        is_list = not is_map
                        post_init_lines.append(
                            make_post_init_line(attr_name, elem_py_type, is_map=is_map, is_list=is_list)
                        )
                else:
                    py_type = type_from_schema_attr(attr, class_name, attr_name)
                field_line = f"    {safe_name(attr_name)}: Optional[{py_type}] = None"
                if attr.required:
                    required_fields.append(field_line)
                    required_attr_names.append(safe_name(attr_name))
                else:
                    optional_fields.append(field_line)

        for block_type_name, block_type in (block.block_types or {}).items():
            is_list = block_type.nesting_mode in ("list", "set")
            is_required = (block_type.min_items or 0) > 0 if is_list else bool(block_type.required)
            add_block_attribute(block_type_name, block_type.block, is_list=is_list, required=is_required)

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
        "import json",
        "import sys",
        "from dataclasses import asdict, dataclass",
        "from typing import Optional, List, Dict, Any, Set, ClassVar",
    ]
    if "Union" in used_types:
        import_lines.append("from typing import Union")
    if "Tuple" in used_types:
        import_lines.append("from typing import Tuple")

    module_str = "\n".join(import_lines + [""] + class_defs + [main_entrypoint()])
    return module_str.strip() + "\n"


def main_entrypoint():
    return """
def main():
    input_data = sys.stdin.read()
    # Parse the input as JSON
    params = json.loads(input_data)
    input_json = params["input_json"]
    resource = Resource(**json.loads(input_json))
    primitive_types = (str, float, bool, int)
    output = {key: value if value is None or isinstance(value, primitive_types) else json.dumps(value) for key, value in asdict(resource).items()}
    output["error_message"] = "" # todo: support better validation
    json_str = json.dumps(output)
    from pathlib import Path
    logs_out = Path(__file__).parent / "logs.json"
    logs_out.write_text(json_str)
    print(json_str)


if __name__ == "__main__":
    main()
"""


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
