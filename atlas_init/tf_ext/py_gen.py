import importlib.util
import inspect
import logging
import re
from dataclasses import Field, fields, is_dataclass
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from types import ModuleType
from typing import Dict, Iterable, List, NamedTuple, Union, get_args, get_origin

from zero_3rdparty import humps
from zero_3rdparty.file_utils import copy

logger = logging.getLogger(__name__)


def import_module_by_using_parents(file_path: Path) -> ModuleType:
    with TemporaryDirectory() as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        module_path = tmp_dir_path / "tmp_module"
        copy(file_path.parent, module_path)
        init_py = module_path / "__init__.py"
        if not init_py.exists():
            init_py.write_text("")
        # old_path = sys.path todo: reset after
        sys.path.insert(0, tmp_dir)
        logger.info("files in tmp_module: " + ", ".join((py.name for py in module_path.glob("*.py"))))
        module = importlib.import_module(f"tmp_module.{file_path.stem}")
        assert module
        if inspect.ismodule(module):
            return module
        raise ImportError(f"Could not import module {file_path.stem} from {file_path}")

        # sys.path.insert(0, str(module_path))
        # try:
        #     module_spec = importlib.util.spec_from_file_location(module_path.name, init_py)
        #     assert module_spec
        #     assert module_spec.loader
        #     parent_module = importlib.util.module_from_spec(module_spec)
        #     module_spec.loader.exec_module(parent_module)

        #     spec_file = importlib.util.spec_from_file_location(dest_path.stem, dest_path)
        #     assert spec_file
        #     assert spec_file.loader
        #     module = importlib.util.module_from_spec(spec_file)
        #     module.__package__ = "tmp_module"
        #     spec_file.loader.exec_module(module)
        #     if inspect.ismodule(module):
        #         return module
        #     raise ImportError(f"Could not import module {file_path.stem} from {file_path}")
        # except Exception as e:
        #     raise e
        # finally:
        #     sys.path = old_path


def import_from_path(module_name: str, file_path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


primitive_types = (str, float, bool, int)


def as_set(values: list[str]) -> str:
    return f"{{{', '.join(repr(v) for v in values)}}}" if values else "set()"


def make_post_init_line_optional(field_name: str, elem_type: str, is_map: bool = False, is_list: bool = False) -> str:
    if is_map:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = {{k:v if isinstance(v, {elem_type}) else {elem_type}(**v) for k, v in self.{field_name}.items()}}"
        )
    elif is_list:
        return (
            f"        if self.{field_name} is not None:\n"
            f"            self.{field_name} = [x if isinstance(x, {elem_type}) else {elem_type}(**x) for x in self.{field_name}]"
        )
    else:
        return (
            f"        if self.{field_name} is not None and not isinstance(self.{field_name}, {elem_type}):\n"
            f'            assert isinstance(self.{field_name}, dict), f"Expected {field_name} to be a {elem_type} or a dict, got {{type(self.{field_name})}}"\n'
            f"            self.{field_name} = {elem_type}(**self.{field_name})"
        )


def make_post_init_line(field_name: str, elem_type: str, is_map: bool = False, is_list: bool = False) -> str:
    if is_map:
        return (
            f'        assert isinstance(self.{field_name}, dict), f"Expected {field_name} to be a dict, got {{type(self.{field_name})}}"\n'
            f"        self.{field_name} = {{k:v if isinstance(v, {elem_type}) else {elem_type}(**v) for k, v in self.{field_name}.items()}}"
        )
    elif is_list:
        return (
            f'        assert isinstance(self.{field_name}, list), f"Expected {field_name} to be a list, got {{type(self.{field_name})}}"\n'
            f"        self.{field_name} = [x if isinstance(x, {elem_type}) else {elem_type}(**x) for x in self.{field_name}]"
        )
    else:
        return (
            f"        if not isinstance(self.{field_name}, {elem_type}):\n"
            f'            assert isinstance(self.{field_name}, dict), f"Expected {field_name} to be a {elem_type} or a dict, got {{type(self.{field_name})}}"\n'
            f"            self.{field_name} = {elem_type}(**self.{field_name})"
        )


class _PrimitiveType(Exception):
    def __init__(self, type_: type):
        self.type_ = type_


def make_post_init_line_from_field(field: Field) -> str:
    field_type = field.type
    origin = get_origin(field_type)
    args = get_args(field_type)

    if origin is Union and type(None) in args:
        non_none_args = [arg for arg in args if arg is not type(None)]
        assert len(non_none_args) == 1, f"Expected one non-None type in Union, got {non_none_args}"
        inner_type = non_none_args[0]
        if inner_type in primitive_types:
            return ""
        try:
            if elem_type := _handle_list_type(inner_type):
                return make_post_init_line_optional(field.name, elem_type, is_list=True)
            if elem_type := _handle_dict_type(inner_type):
                return make_post_init_line_optional(field.name, elem_type, is_map=True)
            return make_post_init_line_optional(field.name, inner_type.__name__)
        except _PrimitiveType:
            return ""
    try:
        if elem_type := _handle_list_type(field_type):
            return make_post_init_line(field.name, elem_type, is_list=True)
        if elem_type := _handle_dict_type(field_type):
            return make_post_init_line(field.name, elem_type, is_map=True)
    except _PrimitiveType:
        return ""
    if field_type not in primitive_types:
        return make_post_init_line(field.name, getattr(field_type, "__name__", str(field_type)))
    return ""


def _handle_list_type(inner_type):
    inner_origin = get_origin(inner_type)
    inner_args = get_args(inner_type)
    if inner_origin in (list, List) and inner_args:
        item_type = inner_args[0]
        if item_type in primitive_types:
            raise _PrimitiveType(item_type)
        return item_type.__name__
    return None


def _handle_dict_type(inner_type):
    inner_origin = get_origin(inner_type)
    inner_args = get_args(inner_type)
    if inner_origin in (dict, Dict) and inner_args:
        _, value_type = inner_args
        if value_type in primitive_types:
            raise _PrimitiveType(value_type)
        return value_type.__name__
    return None


def longest_common_substring_among_all(strings: list[str]) -> str:
    from functools import reduce

    strings = [s.lower() for s in strings]

    def lcs(a, b):
        m = [[0] * (1 + len(b)) for _ in range(1 + len(a))]
        longest, x_longest = 0, 0
        for x in range(1, 1 + len(a)):
            for y in range(1, 1 + len(b)):
                if a[x - 1] == b[y - 1]:
                    m[x][y] = m[x - 1][y - 1] + 1
                    if m[x][y] > longest:
                        longest = m[x][y]
                        x_longest = x
                else:
                    m[x][y] = 0
        return a[x_longest - longest : x_longest]

    return humps.pascalize(reduce(lcs, strings).strip("_"))


_main_call = """
if __name__ == "__main__":
    main()
"""


def move_main_call_to_end(file_path: Path) -> None:
    text = file_path.read_text()
    text = text.replace(_main_call, "")
    file_path.write_text(text + _main_call)


class DataclassMatch(NamedTuple):
    cls_name: str
    match_context: str
    index_start: int
    index_end: int


def dataclass_matches(code: str, cls_name: str) -> Iterable[DataclassMatch]:
    for match in dataclass_pattern(cls_name).finditer(code):
        start = match.start()
        end = code[start:].find("\n\n\n")
        assert end > 0, f"unable to find end of dataclass: {cls_name}"
        yield DataclassMatch(cls_name, code[start - 20 : start + 20], start, start + end + 3)


def dataclass_pattern(cls_name: str) -> re.Pattern:
    return re.compile(rf"@dataclass\nclass {cls_name}(?P<base>\(\w+\))?:")


def dataclass_indexes(code: str, cls_name: str) -> tuple[int, int]:
    matches = list(dataclass_matches(code, cls_name))
    assert len(matches) == 1, f"expected exactly one dataclass match for {cls_name}, got {len(matches)}"
    return matches[0].index_start, matches[0].index_end


def make_post_init(lines: list[str]) -> str:
    return "    def __post_init__(self):\n" + "\n".join(lines)


def module_dataclasses(module: ModuleType) -> dict[str, type]:
    return {
        name: maybe_dc
        for name, maybe_dc in vars(module).items()
        if is_dataclass(maybe_dc) and inspect.isclass(maybe_dc)
    }


def ensure_dataclass_use_conversion(dataclasses: dict[str, type], file_path: Path, skip_filter: set[str]) -> None:
    py_code = file_path.read_text()
    for name, cls in dataclasses.items():
        if name in skip_filter:
            continue
        post_init_lines = [extra_line for field in fields(cls) if (extra_line := make_post_init_line_from_field(field))]
        if not post_init_lines:
            continue
        index_start, cls_def_end = dataclass_indexes(py_code, name)
        old_dc_code = py_code[index_start:cls_def_end]
        if "def __post_init__" in old_dc_code:
            continue  # already exists, don't touch it
        insert_location = old_dc_code.find("\n\n")
        assert insert_location > 0
        new_dc_code = (
            old_dc_code[:insert_location] + "\n\n" + make_post_init(post_init_lines) + old_dc_code[insert_location:]
        )
        py_code = py_code.replace(old_dc_code, new_dc_code)
    file_path.write_text(py_code)
