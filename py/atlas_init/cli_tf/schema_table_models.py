import re
from enum import StrEnum
from functools import total_ordering

from model_lib import Entity, Event
from pydantic import Field

from atlas_init.cli_tf.schema_v3 import ComputedOptionalRequired


class TFSchemaTableColumn(StrEnum):
    Computability = "Computability"
    Type = "Type"
    Default = "Default"
    PlanModifiers = "PlanModifiers"


class FuncCallLine(Event):
    line_nr: int
    func_name: str
    args: str


_schema_type_regex = re.compile(r"schema\.\w+")


@total_ordering
class TFSchemaAttribute(Entity):
    name: str
    default: str = ""
    plan_modifiers: list[str] = Field(default_factory=list)

    line_start: int
    line_end: int
    indent: str = ""
    lines: list[str] = Field(default_factory=list)

    func_call_line: FuncCallLine | None = None
    attribute_path: str = ""
    absolute_attribute_path: str = ""

    @property
    def type(self) -> str:
        if self.lines and (type_match := _schema_type_regex.search(self.lines[0])):
            return type_match.group()
        prefix = f"{self.indent}\tType:"
        for line in self.lines:
            if line.startswith(prefix):
                schema_type = line[len(prefix) :].strip()
                if schema_type.startswith("schema."):
                    return schema_type
        return ""

    @property
    def computability(self) -> ComputedOptionalRequired:
        if self.is_required:
            return ComputedOptionalRequired.required
        optional = self.is_optional
        computed = self.is_computed
        if optional:
            if computed:
                return ComputedOptionalRequired.computed_optional
            return ComputedOptionalRequired.optional
        if computed:
            return ComputedOptionalRequired.computed
        return ComputedOptionalRequired.unset

    @property
    def is_function_call(self) -> bool:
        return self.func_call_line is not None

    @property
    def is_required(self) -> bool:
        prefix = f"{self.indent}\tRequired:"
        return any("true" in line and line.startswith(prefix) for line in self.lines)

    @property
    def is_computed(self) -> bool:
        prefix = f"{self.indent}\tComputed:"
        return any("true" in line and line.startswith(prefix) for line in self.lines)

    @property
    def is_optional(self) -> bool:
        prefix = f"{self.indent}\tOptional:"
        return any("true" in line and line.startswith(prefix) for line in self.lines)

    @property
    def start_end(self) -> tuple[int, int]:
        return self.line_start, self.line_end

    def as_dict(self) -> dict[TFSchemaTableColumn, str]:
        return {
            TFSchemaTableColumn.Computability: self.computability,
            TFSchemaTableColumn.Type: self.type,
            TFSchemaTableColumn.Default: self.default,
            TFSchemaTableColumn.PlanModifiers: ", ".join(self.plan_modifiers),
        }

    def row(self, columns: list[TFSchemaTableColumn]) -> list[str]:
        d = self.as_dict()
        return [d[col] for col in columns]

    def parent_attribute_names(self) -> list[str]:
        parent_path = self.attribute_path.removesuffix(self.name).strip(".")
        parents: list[str] = []
        for parent in parent_path.split("."):
            if not parent:
                continue
            if parent.startswith("(") and parent.endswith(")"):
                parents.extend(parent.strip("()").split("|"))
            else:
                parents.append(parent)

        return parents

    def __lt__(self, other) -> bool:
        if not isinstance(other, TFSchemaAttribute):
            raise TypeError
        return self.absolute_attribute_path < other.absolute_attribute_path
