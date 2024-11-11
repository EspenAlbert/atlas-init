from __future__ import annotations

import logging
import re
from collections import defaultdict
from contextlib import suppress
from typing import NamedTuple

from model_lib import Entity
from pydantic import Field, ValidationError

from atlas_init.cli_tf.schema_table_models import (
    AttrRefLine,
    FuncCallLine,
    TFSchemaAttribute,
)

logger = logging.getLogger(__name__)


class MaybeSchemaAttributeLine(Entity):
    name: str
    rest: str

    @property
    def is_schema_attribute(self) -> bool:
        return self.rest.startswith("schema.")

    @property
    def is_function_call(self) -> bool:
        return self.rest.endswith("),")

    def attr_ref(self, go_code: str, code_lines: list[str], ref_line_nr: int) -> TFSchemaAttribute | None:
        attr_ref = self.rest.lstrip("&").rstrip(",").strip()
        if not attr_ref.isidentifier():
            return None
        if attr_ref == "RSTagsSchema":
            pass
        try:
            _instantiate_regex = re.compile(rf"{attr_ref}\s=\sschema\.\w+\{{$", re.M)
        except re.error:
            return None
        instantiate_match = _instantiate_regex.search(go_code)
        if not instantiate_match:
            return None
        line_start_nr = go_code[: instantiate_match.start()].count("\n") + 1
        line_start = code_lines[line_start_nr]
        attribute = parse_attribute_lines(code_lines, line_start_nr, line_start, self, is_attr_ref=True)
        attribute.attr_ref_line = AttrRefLine(line_nr=ref_line_nr, attr_ref=attr_ref)
        return attribute

    def func_call_line(self, lines: list[str], go_code: str, call_line_nr: int) -> FuncCallLine | None:
        if not self.is_function_call:
            return None
        func_def_line = self._function_line(go_code)
        if not func_def_line:
            return None
        func_name, args = self.rest.split("(", maxsplit=1)
        func_start, func_end = self._func_lines(lines, func_def_line)
        return FuncCallLine(
            call_line_nr=call_line_nr,
            func_name=func_name.strip(),
            args=args.removesuffix("),").strip(),
            func_line_start=func_start,
            func_line_end=func_end,
        )

    def _func_lines(self, lines: list[str], func_def_line: str) -> tuple[int, int]:
        start_line = lines.index(func_def_line)
        for line_nr, line in enumerate(lines[start_line + 1 :], start=start_line + 1):
            if line.rstrip() == "}":
                return start_line, line_nr
        raise ValueError(f"no end line found for {self}")

    def _function_line(self, go_code: str) -> str:
        function_name = self.rest.split("(")[0].strip()
        pattern = re.compile(rf"func {function_name}\(.*\) \*?schema\.\w+ \{{$", re.M)
        match = pattern.search(go_code)
        if not match:
            return ""
        return go_code[match.start() : match.end()]

    def is_schema_func(self, go_code: str) -> bool:
        return bool(self._function_line(go_code))


def parse_attribute_lines(
    lines: list[str],
    line_nr: int,
    line: str,
    attr_line: MaybeSchemaAttributeLine,
    *,
    is_attr_ref: bool = False,
) -> TFSchemaAttribute:
    indents = len(line) - len(line.lstrip())
    indent = indents * "\t"
    end_line = f"{indent}}}" if is_attr_ref else f"{indent}}},"
    for extra_lines, next_line in enumerate(lines[line_nr + 1 :], start=1):
        if next_line == end_line:
            return TFSchemaAttribute(
                name=attr_line.name,
                lines=lines[line_nr : line_nr + extra_lines],
                line_start=line_nr,
                line_end=line_nr + extra_lines,
                indent=indent,
            )
    raise ValueError(f"no end line found for {attr_line.name}, starting on line {line_nr}")


_schema_attribute_go_regex = re.compile(
    r'^\s+"(?P<name>[^"]+)":\s(?P<rest>.+)$',
)


def find_attributes(go_code: str) -> list[TFSchemaAttribute]:
    lines = ["", *go_code.splitlines()]  # support line_nr indexing
    attributes = []
    for line_nr, line in enumerate(lines):
        if match := _schema_attribute_go_regex.match(line):
            with suppress(ValidationError):
                maybe_attribute = MaybeSchemaAttributeLine(
                    name=match.group("name"),
                    rest=match.group("rest"),
                )
                if func_call := maybe_attribute.func_call_line(lines, go_code, line_nr):
                    line_start = func_call.func_line_start
                    line_end = func_call.func_line_end
                    attribute = TFSchemaAttribute(
                        name=maybe_attribute.name,
                        lines=lines[line_start:line_end],
                        line_start=line_start,
                        line_end=line_end,
                        func_call=func_call,
                        indent="\t",
                    )
                elif attribute := maybe_attribute.attr_ref(go_code, lines, line_nr):
                    logger.info(f"attr_ref: {attribute}")
                else:
                    try:
                        attribute = parse_attribute_lines(lines, line_nr, line, maybe_attribute)
                    except ValueError as e:
                        logger.warning(e)
                        continue
                    if not attribute.type:
                        continue
                attributes.append(attribute)
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
