import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from pathlib import Path
from typing import ClassVar, Iterable

import pydot
import typer
from model_lib import Entity, dump, dump_as_dict
from pydantic import Field
from zero_3rdparty.file_utils import ensure_parents_write_text, iter_paths_and_relative

from atlas_init.cli_tf.hcl.parser import iter_resource_blocks
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.provider_schema import AtlasSchemaInfo
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen_provider import parse_atlas_schema_info
from atlas_init.tf_ext.tf_modules import (
    ColorCoderABC,
    create_dot_graph,
    parse_atlas_graph,
    remove_provider_name,
    write_graph,
)
from atlas_init.tf_ext.tf_ws import include_path

logger = logging.getLogger(__name__)


class ExampleSrc(StrEnum):
    Arch = "Arch"
    Provider = "Provider"
    Registry = "Registry"
    UserSpecified = "UserSpecified"


example_sources = [src for src in ExampleSrc if src != ExampleSrc.UserSpecified]


remove_prefixes = {
    ExampleSrc.Arch: "source/includes/examples/tf-example-",
    ExampleSrc.Registry: "Registry",
}


def format_rel_path(src: ExampleSrc, relative_path: str, line_start: int, line_end: int) -> str:
    no_stem, _ = relative_path.rsplit(".", maxsplit=1)
    no_stem = no_stem.removeprefix(remove_prefixes.get(src, ""))
    return f"{src}: {no_stem}#L{line_start}-L{line_end}"


base_urls = {
    ExampleSrc.Arch: "https://github.com/mongodb/docs-atlas-architecture/blob/main/",
    ExampleSrc.Provider: "https://github.com/mongodb/terraform-provider-mongodbatlas/blob/master/examples/",
    ExampleSrc.Registry: "https://github.com/mongodb/terraform-provider-mongodbatlas/blob/master/docs/resources/",
}


def format_url(src: ExampleSrc, relative_path: str, line_start: int, line_end: int) -> str:
    if src == ExampleSrc.UserSpecified:
        return f"{relative_path}#L{line_start}-L{line_end}"
    return f"{base_urls[src]}{relative_path}#L{line_start}-L{line_end}"


def root_path_file_globs(settings: TfExtSettings, example_src: ExampleSrc) -> tuple[Path, list[str]]:
    if example_src == ExampleSrc.Arch:
        path = settings.atlas_arch_center_path
        assert path, "atlas_arch_center_path is not set"
        return path, ["*.rst", "*.md"]
    elif example_src == ExampleSrc.Provider:
        repo_path = settings.repo_path_atlas_provider
        assert repo_path, "repo_path_atlas_provider is not set"
        return repo_path / "examples", ["*.tf"]
    elif example_src == ExampleSrc.Registry:
        repo_path = settings.repo_path_atlas_provider
        assert repo_path, "repo_path_atlas_provider is not set"
        return repo_path / "docs/resources", ["*.md"]
    raise ValueError(f"unknown example source: {example_src}")


@total_ordering
class ExampleSnippet(Entity):
    src: ExampleSrc
    relative_path: str
    line_start: int
    line_end: int
    snippet: str

    def md_link(self) -> str:
        name = format_rel_path(self.src, self.relative_path, self.line_start, self.line_end)
        url = format_url(self.src, self.relative_path, self.line_start, self.line_end)
        return f"[{name}]({url})"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ExampleSnippet):
            raise TypeError(f"cannot compare {type(self)} with {type(other)}")
        return (self.src, self.relative_path) < (other.src, other.relative_path)


@total_ordering
class ResourceRow(Entity):
    provider: str
    name: str
    examples: list[ExampleSnippet] = Field(default_factory=list)
    deprecated: bool = False

    @property
    def full_name(self) -> str:
        return f"{self.provider}_{self.name}"

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ResourceRow):
            raise TypeError(f"cannot compare {type(self)} with {type(other)}")
        return self.full_name < other.full_name

    def has_example(self, src: ExampleSrc) -> bool:
        return any(example.src == src for example in self.examples)


class ResourceUsage(Entity):
    root_path: Path
    rows: dict[str, ResourceRow] = Field(default_factory=dict)

    def add_row(self, row: ResourceRow):
        full_name = row.full_name
        if full_name in self.rows:
            self.rows[full_name].examples.extend(row.examples)
        else:
            self.rows[full_name] = row

    def has_deprecated(self) -> bool:
        return any(row.deprecated for row in self.rows.values())

    def missing_examples(self, src: ExampleSrc) -> list[str]:
        return sorted(name for name, row in self.rows.items() if not row.has_example(src))


def extract_rows(src: ExampleSrc, relative_path: str, text: str, deprecated: set[str]) -> Iterable[ResourceRow]:
    dedented_text = "\n".join(line.lstrip() for line in text.splitlines())
    try:
        for block in iter_resource_blocks(dedented_text):
            provider, resource_type = block.type.split("_", maxsplit=1)
            yield ResourceRow(
                provider=provider,
                name=resource_type,
                deprecated=resource_type in deprecated,
                examples=[
                    ExampleSnippet(
                        src=src,
                        relative_path=relative_path,
                        line_start=block.line_start,
                        line_end=block.line_end,
                        snippet=block.hcl,
                    )
                ],
            )
    except Exception as e:
        logger.warning(f"Failed to extract rows from {relative_path}: {e!r}")
        return


def format_examples_as_html_table_cells(examples: list[ExampleSnippet]) -> str:
    if not examples:
        return ""
    return " • ".join([example.md_link() for example in sorted(examples)])


def dump_usage_md(resource_usage: ResourceUsage, output_path: Path):
    if resource_usage.has_deprecated():
        usage_md = [
            "## Resource Usage",
            "",
            "Name | Examples | Deprecated",
            "--- | --- | ---",
            *[
                f"{row.full_name} | {format_examples_as_html_table_cells(row.examples)} | {row.deprecated}"
                for row in sorted(resource_usage.rows.values())
            ],
            "",
        ]
    else:
        usage_md = [
            "## Resource Usage",
            "",
            "Name | Examples",
            "--- | ---",
            *[
                f"{row.full_name} | {format_examples_as_html_table_cells(row.examples)}"
                for row in sorted(resource_usage.rows.values())
            ],
            "",
        ]
    ensure_parents_write_text(output_path, "\n".join(usage_md))


def iter_rows(src: ExampleSrc, root_path: Path, deprecated: set[str], file_globs: list[str]) -> Iterable[ResourceRow]:
    for tf_path, rel_path in iter_paths_and_relative(root_path, *file_globs, only_files=True):
        logger.debug(f"Processing {tf_path}")
        if not include_path(rel_path):
            logger.debug(f"Skipping {tf_path} because it is in an ignored directory")
            continue
        try:
            text = tf_path.read_text()
        except Exception as e:
            logger.warning(f"Failed to read {tf_path}: {e!r}")
            continue
        yield from extract_rows(src, rel_path, text, deprecated)


def _default_file_glob() -> list[str]:
    return ["*.tf"]


_force_include = {
    "cloud_user_org_assignment",
    "cloud_user_project_assignment",
    "cloud_user_team_assignment",
    "encryption_at_rest_private_endpoint",
    "organization",
    "team_project_assignment",
}


def dump_not_used(info: AtlasSchemaInfo, output_path: Path, usage: ResourceUsage):
    """
    Adds a markdown table:
    Name | Deprecated | Included
    """

    missing_examples = usage.missing_examples(ExampleSrc.Arch)
    atlas_prefix = f"{ATLAS_PROVIDER_NAME}_"
    md = [
        "## Resources Not Used",
        "",
        "Name | Deprecated | Included",
        "--- | --- | ---",
        *[
            f"{name_no_prefix} | {resource_type in info.deprecated_resource_types} | {name_no_prefix in _force_include}"
            for resource_type in missing_examples
            if resource_type.startswith(atlas_prefix) and (name_no_prefix := resource_type.removeprefix(atlas_prefix))
        ],
        "",
    ]
    ensure_parents_write_text(output_path, "\n".join(md))


_resource_ref_pattern = re.compile(r"\s+(?P<resource_type>[\w_]+)\.(?P<resource_label>[\w_-]+)")


def _iter_edges(valid_resource_types: set[str], dest: str, dest_hcl: str) -> Iterable[tuple[str, str]]:
    for ref in _resource_ref_pattern.finditer(dest_hcl):
        src_type = ref.group("resource_type")
        if src_type in valid_resource_types:
            yield src_type, dest


class SimpleGraph(Entity):
    parent_child_edges: dict[str, set[str]] = Field(default_factory=lambda: defaultdict(set))

    def add_edge(self, src: str, dst: str):
        self.parent_child_edges[src].add(dst)

    def flat_edges(self) -> list[tuple[str, str]]:
        return [(src, dst) for src in self.parent_child_edges for dst in self.parent_child_edges[src]]


def build_simple_graph(usage: ResourceUsage) -> SimpleGraph:
    graph = SimpleGraph()
    valid_resource_types = set(usage.rows.keys())
    for dest_resource_type, row in usage.rows.items():
        for example in row.examples:
            for src_ref, dest_ref in _iter_edges(valid_resource_types, dest_resource_type, example.snippet):
                graph.add_edge(src_ref, dest_ref)
    return graph


@dataclass
class ColorCoderSimple(ColorCoderABC):
    keep_provider_name: bool = False

    PROVIDER_COLORS: ClassVar[dict[str, str]] = {
        "aws": "yellow",
        "azurerm": "lightblue",
        "azapi": "lightblue",
        "google": "purple",
        "mongodbatlas": "green",
    }
    ATLAS_DEPRECATED_COLOR: ClassVar[str] = "orange"

    def create_node(self, resource_type: str, *, is_unused: bool = False) -> pydot.Node:
        provider = resource_type.split("_", 1)[0]
        return pydot.Node(
            resource_type, shape="box", style="filled", fillcolor=self.PROVIDER_COLORS.get(provider, "gray")
        )

    def node_name(self, resource_type: str) -> str:
        return resource_type if self.keep_provider_name else remove_provider_name(resource_type)


def tf_resource_usage(
    root_path: Path = typer.Option(
        ...,
        "-p",
        "--root-path",
        default_factory=Path.cwd,
        help="Path to the root directory, will recurse and look for **/*.tf",
    ),
    output_path_str: str = typer.Option(
        "",
        "-o",
        "--output-path",
        help="Path to the output file",
    ),
    file_glob: list[str] = typer.Option(
        ...,
        "-g",
        "--file-glob",
        default_factory=_default_file_glob,
        help="Glob pattern to match files",
    ),
    all_examples: bool = typer.Option(False, "-a", "--all-examples", help="Include all examples"),
):
    settings = TfExtSettings.from_env()
    if not output_path_str:
        output_path = settings.example_usage_output_path
    elif output_path_str.startswith("/"):
        output_path = Path(output_path_str)
    else:
        output_path = root_path / output_path_str

    atlas_graph = parse_atlas_graph(settings)
    deprecated = atlas_graph.deprecated_resource_types
    usage = ResourceUsage(root_path=root_path)
    if all_examples:
        info, _ = parse_atlas_schema_info(settings)
        schema_resource_types = info.resource_types
        for src in example_sources:
            src_path, file_globs = root_path_file_globs(settings, src)
            src_usage = ResourceUsage(root_path=src_path)
            for row in iter_rows(src, src_path, deprecated, file_globs):
                src_usage.add_row(row)
                usage.add_row(row)
            src_output_path = settings.example_usage_output_path_src(src)
            dump_usage_md(src_usage, src_output_path)
        no_examples = set(schema_resource_types) - set(usage.rows.keys())
        if no_examples:
            no_examples_str = "\n".join(no_examples)
            logger.warning(f"Missing examples for {no_examples_str}")
        missing_path = settings.example_missing_md_path(ExampleSrc.Arch)
        dump_not_used(info, missing_path, usage)
        graph = build_simple_graph(usage)
        graph_output = settings.example_graph_path
        graph_dict = dict(sorted(dump_as_dict(graph.parent_child_edges).items()))
        graph_yaml = dump(graph_dict, "yaml")
        ensure_parents_write_text(graph_output, graph_yaml)
        logger.info(f"Example graph written to {graph_output}")
        dot_graph = create_dot_graph(
            "Example Graph", graph.flat_edges(), color_coder=ColorCoderSimple(keep_provider_name=True)
        )
        graph_output_dir = settings.example_graph_path.parent
        graph_name = settings.example_graph_path.stem
        write_graph(dot_graph, graph_output_dir, graph_name)
        logger.info(f"Example graph written to {graph_output_dir}/{graph_name}.*")
    else:
        for row in iter_rows(ExampleSrc.UserSpecified, root_path, deprecated, file_glob):
            usage.add_row(row)
    dump_usage_md(usage, output_path)
    logger.info(f"Resource usage written to {output_path}")
    return usage
