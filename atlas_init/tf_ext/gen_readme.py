from __future__ import annotations

import logging
import re
from contextlib import suppress
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable, Self, TypeAlias

from ask_shell.shell import run_and_wait
from model_lib import Entity, parse_model
from pydantic import Field, ValidationError, model_validator
from zero_3rdparty.file_utils import ensure_parents_write_text, update_between_markers

from atlas_init.cli_tf.go_test_summary import markdown_table_lines
from atlas_init.tf_ext.gen_examples import read_example_dirs
from atlas_init.tf_ext.models_module import (
    EXAMPLES_DIRNAME,
    README_FILENAME,
    TERRAFORM_DOCS_CONFIG_FILENAME,
    resolve_terraform_docs_config_path,
)

logger = logging.getLogger(__name__)
_readme_disclaimer = """\
## Disclaimer
This Module is not meant for external consumption.
It is part of a development PoC.
Any usage problems will not be supported.
However, if you have any ideas or feedback, feel free to open a Github Issue!
"""


class ReadmeMarker(StrEnum):
    DISCLAIMER = "DISCLAIMER"
    MODULES = "MODULES"
    EXAMPLE = "TF_EXAMPLES"
    TF_DOCS = "TF_DOCS"
    TABLES = "TABLES"

    @classmethod
    def find_markers(cls, readme_content: str, ignored_markers: list[str]) -> list[str]:
        found = []
        for marker in list(cls):
            if marker in ignored_markers:
                continue
            if cls.as_start(marker) in readme_content and cls.as_end(marker) in readme_content:
                found.append(marker)
        return found

    @classmethod
    def as_start(cls, marker_name: str) -> str:
        return f"<!-- BEGIN_{marker_name} -->"

    @classmethod
    def as_end(cls, marker_name: str) -> str:
        return f"<!-- END_{marker_name} -->"

    @classmethod
    def marker_lines(cls, marker_name: str) -> str:
        return f"""\
{cls.as_start(marker_name)}

{cls.as_end(marker_name)}
"""

    @classmethod
    def example_boilerplate(cls) -> str:
        return "\n".join(cls.marker_lines(marker_name) for marker_name in list(cls))

    @classmethod
    def readme_generators(cls) -> ReadmeGenerators:
        return {
            cls.DISCLAIMER: lambda _: _readme_disclaimer,
            cls.EXAMPLE: lambda workspace: read_examples(workspace / EXAMPLES_DIRNAME),
            cls.TABLES: lambda workspace: tables_generator(workspace / EXAMPLES_DIRNAME),
        }


ReadmeGenerators: TypeAlias = dict[ReadmeMarker, Callable[[Path], str]]


class ExampleRow(Entity):
    folder: int | str

    @property
    def folder_prefix(self) -> str:
        folder = self.folder
        return f"{folder:02d}" if isinstance(folder, int) else folder

    def match_folder(self, path: Path) -> bool:
        return path.name.startswith(self.folder_prefix)

    def as_replacements(self, folder: Path) -> dict[str, Any]:
        return self.model_dump() | {"folder": folder.name}


class VersionsTFModification(Entity):
    add: str


class ExamplesReadme(Entity):
    readme_template: str
    # user_agent_extra = {}
    # some template vars have a condition
    versions_tf: VersionsTFModification | None = None


class TableConfig(Entity):
    name: str
    columns: list[str] = Field(default_factory=list)
    link_column: str
    example_rows: list[ExampleRow]

    @property
    def column_headers(self) -> list[str]:
        return [col.replace("_", " ").title() for col in self.columns]

    @model_validator(mode="after")
    def checks(self) -> Self:
        assert self.link_column in self.columns, f"link column: {self.link_column} not found in {self.columns}"
        return self


class TablesConfig(Entity):
    tables: list[TableConfig]


class ExamplesReadmeGeneration(Entity):
    tables: list[TableConfig]
    examples_readme: ExamplesReadme
    example_paths: list[Path]
    workspace: Path

    def find_example_row(self, row_path: Path) -> ExampleRow:
        for table in self.tables:
            for row in table.example_rows:
                if row.match_folder(row_path):
                    return row
        raise ValueError(f"unable to find a tables[*].example_rows for directory: {row_path}")


def examples_readme_md_config(workspace: Path) -> ExamplesReadmeGeneration | None:
    examples = read_example_dirs(workspace / EXAMPLES_DIRNAME)
    with suppress(AssertionError, ValidationError):
        config_path = resolve_terraform_docs_config_path(workspace)
        config_content = config_path.read_text()
        return parse_model(
            config_content,
            t=ExamplesReadmeGeneration,
            format="yaml",
            extra_kwargs=dict(example_paths=examples, workspace=workspace),
        )


def generate_examples_readme_from_template(config: ExamplesReadmeGeneration):
    template_path = config.workspace / config.examples_readme.readme_template
    template = template_path.read_text()
    versions_tf_path = config.workspace / "versions.tf"
    assert versions_tf_path, f"no versions.tf file found {config.workspace}"
    template_versions_tf = versions_tf_path.read_text()
    for path in config.example_paths:
        row = config.find_example_row(path)
        replacements = row.as_replacements(path)
        readme_md = template
        for key, value in replacements.items():
            replace_in = "{{ .%s }}" % key.upper()
            replace_out = str(value)
            readme_md = readme_md.replace(replace_in, replace_out)
        readme_md_path = path / README_FILENAME
        readme_md_path.write_text(readme_md)
        if versions_tf_modification := config.examples_readme.versions_tf:
            if add := versions_tf_modification.add:
                versions_tf = f"{template_versions_tf}\n{add}"
                (path / "versions.tf").write_text(versions_tf)


def find_attribute_value(path: Path, attribute_name: str) -> str:
    assert path.is_dir(), "expected a terraform workspace dir"
    pattern = re.compile(rf"^\s+{attribute_name}\s*=(?P<value>.*)$", re.M)
    candidates = []
    for tf_file in path.glob("*.tf"):
        candidates.extend(match["value"].strip().strip('"') for match in pattern.finditer(tf_file.read_text()))
    assert candidates, f"unable to find {attribute_name} in {path}"
    assert len(candidates) == 1, f"more than one candidate for {attribute_name}: {candidates} in @{path}"
    return candidates[0]


def as_markdown_table(examples: list[Path], config: TableConfig) -> list[str]:
    def as_row(row: ExampleRow) -> list[str]:
        example = next((example for example in examples if row.match_folder(example)), None)
        assert example, f"unable to find example for table, {config.name}, in {EXAMPLES_DIRNAME}/{row.folder_prefix}*"
        md_row = []
        for col in config.columns:
            value = getattr(row, col, "") or find_attribute_value(example, col)
            assert isinstance(value, str), f"found unexpected type for {col}: {value!r}"
            if col == config.link_column:
                md_row.append(f"[{value}](./{EXAMPLES_DIRNAME}/{example.name})")
            else:
                md_row.append(value)
        return md_row

    return markdown_table_lines(config.name.title(), config.example_rows, config.column_headers, as_row)


def tables_generator(examples_dir: Path) -> str:
    config = resolve_terraform_docs_config_path(examples_dir.parent)
    parsed = parse_model(config.read_text(), format="yaml", t=TablesConfig)
    examples = read_example_dirs(examples_dir)
    md_content = ["\n".join(as_markdown_table(examples, table_config)) for table_config in parsed.tables]
    return "\n\n".join(md_content)  # separate tables with double line-break


def read_examples(examples_dir: Path) -> str:
    example_dirs = read_example_dirs(examples_dir)
    if not example_dirs:
        return ""
    # ensure the examples are formatted first
    run_and_wait("terraform fmt -recursive .", cwd=examples_dir.parent, allow_non_zero_exit=True, ansi_content=False)
    content = ["# Examples"]
    for example_dir in example_dirs:
        example_name = example_dir.name
        header_name = example_name.replace("_", " ").replace("-", " ").title()
        main_path = example_dir / "main.tf"
        assert main_path.exists(), f"{main_path} does not exist, every example must have a main.tf"
        content.extend(
            [
                f"## [{header_name}](./examples/{example_name})",
                "",
                "```terraform",
                main_path.read_text(),
                "```",
                "",
                "",
            ]
        )
    return "\n".join(content)


_static_terraform_config = """\
formatter: markdown document
output:
  file: "FILENAME"
  mode: inject
  template: |-
    START_MARKER
    {{ .Content }}
    END_MARKER
sort:
  enabled: true
  by: required
"""


def terraform_docs_config_content(readme_path: Path) -> str:
    config = _static_terraform_config
    for replacement_in, replacement_out in [
        ("FILENAME", readme_path.name),
        ("START_MARKER", ReadmeMarker.as_start(ReadmeMarker.TF_DOCS)),
        ("END_MARKER", ReadmeMarker.as_end(ReadmeMarker.TF_DOCS)),
    ]:
        config = config.replace(replacement_in, replacement_out)
    return config


def generate_and_write_readme(terraform_workdir: Path, *, generators: ReadmeGenerators | None = None) -> str:
    generators = generators or ReadmeMarker.readme_generators()
    readme_path = resolve_readme_path(terraform_workdir)
    for marker, generator in generators.items():
        content = generator(terraform_workdir)
        if not content:
            continue
        update_between_markers(
            readme_path,
            content,
            ReadmeMarker.as_start(marker),
            ReadmeMarker.as_end(marker),
        )
    # generate_terraform_docs(readme_path)
    logger.info(f"updated {readme_path}")
    return readme_path.read_text()


def resolve_readme_path(terraform_workdir: Path) -> Path:
    readme_path = terraform_workdir / README_FILENAME
    if not readme_path.exists():
        path_lower = readme_path.with_name(readme_path.name.lower())
        if path_lower.exists():
            readme_path = path_lower
    assert readme_path.exists(), (
        f"{readme_path} does not exist, currently a boilerplate is expected, consider adding to {readme_path}\n{ReadmeMarker.example_boilerplate()}"
    )
    return readme_path


def generate_terraform_docs(readme_path: Path) -> None:
    docs_config_path = readme_path.parent / TERRAFORM_DOCS_CONFIG_FILENAME
    if docs_config_path.exists():
        logger.warning(f"{docs_config_path} already exists, skipping generation")
    else:
        config_content = terraform_docs_config_content(readme_path)
        ensure_parents_write_text(docs_config_path, config_content)
        logger.info(f"generated {docs_config_path}")
    run_and_wait(f"terraform-docs -c {docs_config_path} .", cwd=readme_path.parent)
    readme_content = _default_link_updater(readme_path.read_text())
    ensure_parents_write_text(readme_path, readme_content)


def _default_link_updater(readme_content: str) -> str:  # can be a global replacer for now
    for replace_in, replace_out in {
        "docs/resources/advanced_cluster": r"docs/resources/advanced_cluster%2520%2528preview%2520provider%25202.0.0%2529"
    }.items():
        readme_content = readme_content.replace(replace_in, replace_out)
    return readme_content
