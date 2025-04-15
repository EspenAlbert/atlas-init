# pyright: reportIncompatibleMethodOverride=none
from collections import defaultdict
from collections.abc import Iterable
from functools import total_ordering
from pathlib import Path
from typing import Literal, TypeAlias

from model_lib import Entity, Event
from pydantic import Field, model_validator
from zero_3rdparty import iter_utils

from atlas_init.cli_tf.schema_go_parser import parse_schema_functions
from atlas_init.cli_tf.schema_table_models import TFSchemaAttribute, TFSchemaTableColumn
from atlas_init.settings.path import default_factory_cwd


def default_table_columns() -> list[TFSchemaTableColumn]:
    return [TFSchemaTableColumn.Computability]


def file_name_path(file: str) -> tuple[str, Path]:
    if ":" in file:
        file, path = file.split(":", 1)
        return file, Path(path)
    path = Path(file)
    return f"{path.parent.name}/{path.stem}"[:20], path


@total_ordering
class TFSchemaSrc(Event):
    name: str
    file_path: Path | None = None
    url: str = ""

    @model_validator(mode="after")
    def validate(self):
        assert self.file_path or self.url, "must provide file path or url"
        if self.file_path:
            assert self.file_path.exists(), f"file does not exist for {self.name}: {self.file_path}"
        return self

    def __lt__(self, other) -> bool:
        if not isinstance(other, TFSchemaSrc):
            raise TypeError
        return self.name < other.name

    def go_code(self) -> str:
        if path := self.file_path:
            return path.read_text()
        raise NotImplementedError


TableOutputFormats: TypeAlias = Literal["md"]


class TFSchemaTableInput(Entity):
    sources: list[TFSchemaSrc] = Field(default_factory=list)
    output_format: TableOutputFormats = "md"
    output_path: Path = Field(default_factory=default_factory_cwd("schema_table.md"))
    columns: list[TFSchemaTableColumn] = Field(default_factory=default_table_columns)
    explode_rows: bool = False

    @model_validator(mode="after")
    def validate(self):
        assert self.columns, "must provide at least 1 column"
        self.columns = sorted(self.columns)
        assert self.sources, "must provide at least 1 source"
        self.sources = sorted(self.sources)
        assert len(self.sources) == len(set(self.sources)), f"duplicate source names: {self.source_names}"
        return self

    @property
    def source_names(self) -> list[str]:
        return [s.name for s in self.sources]

    def headers(self) -> list[str]:
        return ["Attribute Name"] + [f"{name}-{col}" for name in self.source_names for col in self.columns]


@total_ordering
class TFSchemaTableData(Event):
    source: TFSchemaSrc
    schema_path: str = ""  # e.g., "" is root, "replication_specs.region_config"
    attributes: list[TFSchemaAttribute] = Field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.schema_path}:{self.source.name}"

    def __lt__(self, other) -> bool:
        if not isinstance(other, TFSchemaTableData):
            raise TypeError
        return self.id < other.id


def sorted_schema_paths(schema_paths: Iterable[str]) -> list[str]:
    return sorted(schema_paths, key=lambda x: (x.count("."), x.split(".")[-1]))


class RawTable(Event):
    columns: list[str]
    rows: list[list[str]]


def merge_tables(config: TFSchemaTableInput, schema_path: str, tables: list[TFSchemaTableData]) -> RawTable:
    if schema_path != "":
        raise NotImplementedError
    columns = config.headers()
    if len(tables) > 1:
        err_msg = "only 1 table per schema path supported"
        raise NotImplementedError(err_msg)
    table = tables[0]
    rows = [[attr.absolute_attribute_path, *attr.row(config.columns)] for attr in table.attributes]
    return RawTable(columns=columns, rows=rows)


def format_table(table: RawTable, table_format: TableOutputFormats) -> list[str]:
    # sourcery skip: merge-list-append
    assert table_format == "md", "only markdown format supported"
    lines = []
    lines.append("|".join(table.columns))
    lines.append("|".join(["---"] * len(table.columns)))
    lines.extend("|".join(row) for row in table.rows)
    return lines


def explode_attributes(attributes: list[TFSchemaAttribute]) -> list[TFSchemaAttribute]:
    return sorted(iter_utils.flat_map(attr.explode() for attr in attributes))


def schema_table(config: TFSchemaTableInput) -> str:
    path_tables: dict[str, list[TFSchemaTableData]] = defaultdict(list)
    for source in config.sources:
        go_code = source.go_code()
        attributes, functions = parse_schema_functions(go_code)
        if config.explode_rows:
            attributes = explode_attributes(attributes)
        schema_path = ""  # using only root for now
        path_tables[schema_path].append(
            TFSchemaTableData(source=source, attributes=attributes, schema_path=schema_path)
        )
    output_lines = []
    for schema_path in sorted_schema_paths(path_tables.keys()):
        tables = path_tables[schema_path]
        table = merge_tables(config, schema_path, tables)
        output_lines.extend(["", f"## {schema_path or 'Root'}", ""])
        output_lines.extend(format_table(table, table_format=config.output_format))
    return "\n".join(output_lines)
