from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import NamedTuple

from model_lib import Entity
from pydantic import Field

from atlas_init.cli_tf.schema_table_models import (
    AttrRefLine,
    FuncCallLine,
    TFSchemaAttribute,
)

logger = logging.getLogger(__name__)


def parse_attribute_ref(
    name: str, rest: str, go_code: str, code_lines: list[str], ref_line_nr: int
) -> TFSchemaAttribute | None:
    attr_ref = rest.lstrip("&").rstrip(",").strip()
    if not attr_ref.isidentifier():
        return None
    try:
        _instantiate_regex = re.compile(rf"{attr_ref}\s=\sschema\.\w+\{{$", re.M)
    except re.error:
        return None
    instantiate_match = _instantiate_regex.search(go_code)
    if not instantiate_match:
        return None
    line_start_nr = go_code[: instantiate_match.start()].count("\n") + 1
    line_start = code_lines[line_start_nr]
    attribute = parse_attribute_lines(code_lines, line_start_nr, line_start, name, is_attr_ref=True)
    attribute.attr_ref_line = AttrRefLine(line_nr=ref_line_nr, attr_ref=attr_ref)
    return attribute


def parse_func_call_line(
    name: str, rest: str, lines: list[str], go_code: str, call_line_nr: int
) -> TFSchemaAttribute | None:
    func_def_line = _function_line(rest, go_code)
    if not func_def_line:
        return None
    func_name, args = rest.split("(", maxsplit=1)
    func_start, func_end = _func_lines(name, lines, func_def_line)
    call = FuncCallLine(
        call_line_nr=call_line_nr,
        func_name=func_name.strip(),
        args=args.removesuffix("),").strip(),
        func_line_start=func_start,
        func_line_end=func_end,
    )
    return TFSchemaAttribute(
        name=name,
        lines=lines[func_start:func_end],
        line_start=func_start,
        line_end=func_end,
        func_call=call,
        indent="\t",
    )


def _func_lines(name: str, lines: list[str], func_def_line: str) -> tuple[int, int]:
    start_line = lines.index(func_def_line)
    for line_nr, line in enumerate(lines[start_line + 1 :], start=start_line + 1):
        if line.rstrip() == "}":
            return start_line, line_nr
    raise ValueError(f"no end line found for {name} on line {start_line}: {func_def_line}")


def _function_line(rest: str, go_code: str) -> str:
    function_name = rest.split("(")[0].strip()
    pattern = re.compile(rf"func {function_name}\(.*\) \*?schema\.\w+ \{{$", re.M)
    match = pattern.search(go_code)
    if not match:
        return ""
    return go_code[match.start() : match.end()]


def parse_attribute_lines(
    lines: list[str],
    line_nr: int,
    line: str,
    name: str,
    *,
    is_attr_ref: bool = False,
) -> TFSchemaAttribute:
    indents = len(line) - len(line.lstrip())
    indent = indents * "\t"
    end_line = f"{indent}}}" if is_attr_ref else f"{indent}}},"
    for extra_lines, next_line in enumerate(lines[line_nr + 1 :], start=1):
        if next_line == end_line:
            return TFSchemaAttribute(
                name=name,
                lines=lines[line_nr : line_nr + extra_lines],
                line_start=line_nr,
                line_end=line_nr + extra_lines,
                indent=indent,
            )
    raise ValueError(f"no end line found for {name}, starting on line {line_nr}")


_schema_attribute_go_regex = re.compile(
    r'^\s+"(?P<name>[^"]+)":\s(?P<rest>.+)$',
)


def find_attributes(go_code: str) -> list[TFSchemaAttribute]:
    lines = ["", *go_code.splitlines()]  # support line_nr indexing
    attributes = []
    for line_nr, line in enumerate(lines):
        match = _schema_attribute_go_regex.match(line)
        if not match:
            continue
        name = match.group("name")
        rest = match.group("rest")
        if rest.endswith("),"):
            if attr := parse_func_call_line(name, rest, lines, go_code, line_nr):
                attributes.append(attr)
        elif attr := parse_attribute_ref(name, rest, go_code, lines, line_nr):
            attributes.append(attr)
        else:
            try:
                attr = parse_attribute_lines(lines, line_nr, line, name)
            except ValueError as e:
                logger.warning(e)
                continue
            if not attr.type:
                continue
            attributes.append(attr)
    set_attribute_paths(attributes)
    return attributes


class StartEnd(NamedTuple):
    start: int
    end: int
    name: str
    func_call_line: FuncCallLine | None

    def has_parent(self, other: StartEnd) -> bool:
        if self.name == other.name:
            return False
        if func_call := self.func_call_line:
            func_call_line = func_call.call_line_nr
            return other.start < func_call_line < other.end
        return self.start > other.start and self.end < other.end


def set_attribute_paths(attributes: list[TFSchemaAttribute]) -> list[TFSchemaAttribute]:
    start_stops = [StartEnd(a.line_start, a.line_end, a.name, a.func_call) for a in attributes]
    overlaps = [
        (attribute, [other for other in start_stops if start_stop.has_parent(other)])
        for attribute, start_stop in zip(attributes, start_stops, strict=False)
    ]
    for attribute, others in overlaps:
        if not others:
            attribute.attribute_path = attribute.name
            continue
        overlaps = defaultdict(list)
        for other in others:
            overlaps[(other.start, other.end)].append(other.name)
        paths = []
        for names in overlaps.values():
            if len(names) == 1:
                paths.append(names[0])
            else:
                paths.append(f"({'|'.join(names)})")
        paths.append(attribute.name)
        attribute.attribute_path = ".".join(paths)
    return attributes


class GoSchemaFunc(Entity):
    name: str
    line_start: int
    line_end: int
    call_attributes: list[TFSchemaAttribute] = Field(default_factory=list)
    attributes: list[TFSchemaAttribute] = Field(default_factory=list)

    @property
    def attribute_names(self) -> set[str]:
        return {a.name for a in self.call_attributes}

    @property
    def attribute_paths(self) -> str:
        paths = set()
        for a in self.call_attributes:
            path = ".".join(a.parent_attribute_names())
            paths.add(path)
        return f"({'|'.join(paths)})" if len(paths) > 1 else paths.pop()

    def contains_attribute(self, attribute: TFSchemaAttribute) -> bool:
        names = self.attribute_names
        return any(parent_attribute in names for parent_attribute in attribute.parent_attribute_names())


def find_schema_functions(attributes: list[TFSchemaAttribute]) -> list[GoSchemaFunc]:
    function_call_attributes = defaultdict(list)
    for a in attributes:
        if a.is_function_call:
            call = a.func_call
            assert call
            function_call_attributes[call.func_name].append(a)
    root_function = GoSchemaFunc(name="", line_start=0, line_end=0)
    functions: list[GoSchemaFunc] = [
        GoSchemaFunc(
            name=name,
            line_start=func_attributes[0].line_start,
            line_end=func_attributes[0].line_end,
            call_attributes=func_attributes,
        )
        for name, func_attributes in function_call_attributes.items()
    ]
    for attribute in attributes:
        if match_functions := [func for func in functions if func.contains_attribute(attribute)]:
            func_names = [func.name for func in match_functions]
            err_msg = f"multiple functions found for {attribute.name}, {func_names}"
            assert len(match_functions) == 1, err_msg
            function = match_functions[0]
            function.attributes.append(attribute)
            attribute.absolute_attribute_path = f"{function.attribute_paths}.{attribute.attribute_path}".lstrip(".")
        else:
            root_function.attributes.append(attribute)
            attribute.absolute_attribute_path = attribute.attribute_path
    return [root_function, *functions]


def parse_schema_functions(
    go_code: str,
) -> tuple[list[TFSchemaAttribute], list[GoSchemaFunc]]:
    attributes = find_attributes(go_code)
    functions = find_schema_functions(attributes)
    return sorted(attributes), functions
