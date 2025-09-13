import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from pathlib import Path
from typing import ClassVar, Iterable

from ask_shell import new_task, run_and_wait
import pydot
import typer
from model_lib import Entity, dump, dump_as_dict
from pydantic import Field
from zero_3rdparty.file_utils import ensure_parents_write_text, iter_paths_and_relative
from zero_3rdparty.iter_utils import flat_map

from atlas_init.cli_tf.hcl.parser import iter_resource_blocks
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.provider_schema import AtlasSchemaInfo
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen_provider import parse_atlas_schema_info
from atlas_init.tf_ext.constants import provider_name, resource_name
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


class Provider(StrEnum):
    AWS = "aws"
    AZURERM = "azurerm"
    AZAPI = "azapi"
    GOOGLE = "google"
    MONGODBATLAS = "mongodbatlas"


_provider_urls = {
    Provider.AWS: "https://github.com/hashicorp/terraform-provider-aws",
    Provider.AZURERM: "https://github.com/hashicorp/terraform-provider-azurerm",
    Provider.AZAPI: "https://github.com/azure/terraform-provider-azapi",
    Provider.GOOGLE: "https://github.com/hashicorp/terraform-provider-google",
    Provider.MONGODBATLAS: "https://github.com/mongodb/terraform-provider-mongodbatlas",
}


def provider_git_repourl(provider: Provider) -> str:
    return _provider_urls[provider]


def provider_docs_url(resource: str) -> str:
    provider = provider_name(resource)
    return f"https://registry.terraform.io/providers/{provider}/latest/docs/resources/{resource}"


_docs_relative_dir = {
    Provider.AWS: "website/docs/r",
    Provider.AZURERM: "website/docs/r",
    Provider.AZAPI: "website/docs/r",
    Provider.GOOGLE: "website/docs/r",
    Provider.MONGODBATLAS: "docs/resources",
}

_docs_file_extension = {
    Provider.AWS: "html.markdown",
    Provider.AZURERM: "html.markdown",
    Provider.AZAPI: "html.markdown",
    Provider.GOOGLE: "html.markdown",
    Provider.MONGODBATLAS: "md",
}


class UnsupportedProvider(Exception):
    pass


def provider_docs_md_path(root_path: Path, resource_type: str) -> Path:
    provider: Provider = provider_name(resource_type)  # pyright: ignore[reportAssignmentType]
    if provider not in Provider:
        raise UnsupportedProvider(f"provider {provider} is not supported, only {list(Provider)} are supported")
    name = resource_name(resource_type)
    provider_repo_dir = root_path / provider
    if not provider_repo_dir.exists():
        run_and_wait(f"git clone {provider_git_repourl(provider)} {provider_repo_dir}")
    return provider_repo_dir / _docs_relative_dir[provider] / f"{name}.{_docs_file_extension[provider]}"


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
    ROOT_NODE: ClassVar[str] = "root"
    parent_child_edges: dict[str, set[str]] = Field(default_factory=lambda: defaultdict(set))

    def add_edge(self, src: str, dst: str):
        if src == dst:
            return
        self.parent_child_edges[src].add(dst)

    def add_root_node(self, node: str):
        children = self.parent_child_edges.setdefault(self.ROOT_NODE, set())
        children.add(node)

    def flat_edges(self) -> list[tuple[str, str]]:
        return [(src, dst) for src in self.parent_child_edges for dst in self.parent_child_edges[src]]

    @property
    def all_nodes(self) -> set[str]:
        return set(flat_map(self.flat_edges()))

    def to_dot_graph(self, name: str, *, keep_provider_name: bool = True) -> pydot.Dot:
        return create_dot_graph(
            name, self.flat_edges(), color_coder=ColorCoderSimple(keep_provider_name=keep_provider_name)
        )


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

    def get_color(self, resource_type: str, *, is_unused: bool = False) -> str:
        if is_unused:
            return "red"
        provider = resource_type.split("_", 1)[0]
        return self.PROVIDER_COLORS.get(provider, "gray")

    def create_node(self, resource_type: str, *, is_unused: bool = False) -> pydot.Node:
        return pydot.Node(
            resource_type, shape="box", style="filled", fillcolor=self.get_color(resource_type, is_unused=is_unused)
        )

    def node_name(self, resource_type: str) -> str:
        return resource_type if self.keep_provider_name else remove_provider_name(resource_type)


def gather_example_usage(settings: TfExtSettings, usage: ResourceUsage, task: new_task) -> None:
    info, _ = parse_atlas_schema_info(settings)
    deprecated = set(info.deprecated_resource_types)
    schema_resource_types = info.resource_types
    for src in example_sources:
        src_path, file_globs = root_path_file_globs(settings, src)
        src_usage = ResourceUsage(root_path=src_path)
        for row in iter_rows(src, src_path, deprecated, file_globs):
            src_usage.add_row(row)
            usage.add_row(row)
        src_output_path = settings.example_usage_output_path_src(src)
        dump_usage_md(src_usage, src_output_path)
        task.update(advance=1)
    no_examples = set(schema_resource_types) - set(usage.rows.keys())
    if no_examples:
        no_examples_str = "\n".join(no_examples)
        logger.warning(f"Missing examples for {no_examples_str}")
    missing_path = settings.example_missing_md_path(ExampleSrc.Arch)
    dump_not_used(info, missing_path, usage)


def dump_resource_markdown(
    settings: TfExtSettings, usage: ResourceUsage, task: new_task, *, with_full_example: bool = False
) -> None:
    for resource, row in usage.rows.items():
        try:
            docs_path = provider_docs_md_path(settings.provider_base_repo_path, resource)
            if not docs_path.exists():
                if resource in {
                    "mongodbatlas_cloud_provider_access_authorization",
                    "mongodbatlas_cloud_provider_access_setup",
                }:
                    # for some reason these are combined into one file in the provider docs
                    docs_path = provider_docs_md_path(
                        settings.provider_base_repo_path, "mongodbatlas_cloud_provider_access"
                    )
                    logger.warning(f"Docs path for {resource} does not exist, using {docs_path} instead")
                else:
                    logger.warning(f"Docs path for {resource} does not exist")
                    continue
        except UnsupportedProvider:
            logger.warning(f"Unsupported provider for {resource}")
            continue
        markdown_path = settings.resource_markdown_path(resource, with_full_example=with_full_example)
        examples = sorted(
            [row for row in row.examples if row.src not in {ExampleSrc.Registry}]
        )  # registry examples are already included from the provider docs path
        example_lines = []
        for example in examples:
            if with_full_example:
                root_path, _ = root_path_file_globs(settings, example.src)
                example_path = root_path / example.relative_path
                example_text = example_path.read_text()
                example_lines.append(f"### {example.md_link()}\n\n```hcl\n{example_text}\n```\n\n")
            else:
                example_lines.append(f"### {example.md_link()}\n\n```hcl\n{example.snippet}\n```\n\n")
        md_content = [
            f"# {resource}",
            "",
            docs_path.read_text(),
            "",
            "## Examples",
            "",
            *example_lines,
        ]
        ensure_parents_write_text(markdown_path, "\n".join(md_content))
        task.update(advance=1)


def write_graphs(settings: TfExtSettings, usage: ResourceUsage) -> None:
    graph = build_simple_graph(usage)
    graph_output = settings.example_graph_path
    graph_dict = dict(sorted(dump_as_dict(graph.parent_child_edges).items()))
    graph_yaml = dump(graph_dict, "yaml")
    ensure_parents_write_text(graph_output, graph_yaml)
    logger.info(f"Example graph written to {graph_output}")
    dot_graph = graph.to_dot_graph("Full Example Graph", keep_provider_name=True)
    graph_output_dir = settings.example_graph_path.parent
    graph_name = settings.example_graph_path.stem
    write_graph(dot_graph, graph_output_dir, graph_name)
    logger.info(f"Example graph written to {graph_output_dir}/{graph_name}.*")


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
    with_full_example: bool = typer.Option(
        False, "-full", "--with-full-example", help="Include full examples in the resource markdown"
    ),
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
        with new_task("Gather example usage", total=len(example_sources)) as task:
            gather_example_usage(settings, usage, task)
        resource_count = len(usage.rows)
        with new_task("Dump resource markdown", total=resource_count) as task:
            dump_resource_markdown(settings, usage, task, with_full_example=with_full_example)
        with new_task("Write graphs") as task:
            write_graphs(settings, usage)
    else:
        with new_task("Gather user specified usage") as task:
            for row in iter_rows(ExampleSrc.UserSpecified, root_path, deprecated, file_glob):
                usage.add_row(row)
                task.update(advance=1)
    dump_usage_md(usage, output_path)
    logger.info(f"Resource usage written to {output_path}")
    return usage
