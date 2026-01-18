from enum import StrEnum
from pathlib import Path
from typing import Iterable, Self

import typer
from ask_shell import console
from model_lib import Entity
from model_lib.serialize import parse_dict, parse_model
from pydantic import Field, model_validator
from rich.tree import Tree
from zero_3rdparty.iter_utils import flat_map

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME, provider_name
from atlas_init.tf_ext.models import choose_next_emoji
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen_provider import parse_atlas_schema_info
from atlas_init.tf_ext.tf_modules import ColorCoderABC, write_graph
from atlas_init.tf_ext.tf_resource_usage import ColorCoderSimple, SimpleGraph


def _atlas_provider_only() -> list[str]:
    return [ATLAS_PROVIDER_NAME]


class SkipEdgeReason(StrEnum):
    NOT_EXPLORABLE_EDGE = "not_explorable_edge"
    FORCE_SKIP_CHILD = "force_skip_child"
    FORCE_SKIP_PARENT = "force_skip_parent"
    PROVIDER_PARENT_NOT_INCLUDED = "provider_parent_not_included"
    PROVIDER_CHILD_NOT_INCLUDED = "provider_child_not_included"


class ModuleConfig2(Entity):
    name: str = Field(..., description="Name of the module.")
    root_resource_types: list[str] = Field(..., description="List of root resource types for the module.")
    explore_resource_types: list[str] = Field(
        default_factory=list, description="List of resource types that should be explored (parents&children)."
    )
    force_edges: list[str] = Field(default_factory=list, description="List of edges that should always be included.")
    force_include_children: list[str] = Field(
        default_factory=list, description="List of resource types that should always be included as children."
    )
    force_include_parents: list[str] = Field(
        default_factory=list, description="List of resource types that should always be included as parents."
    )
    force_skip_parents: list[str] = Field(
        default_factory=list, description="List of resource types that should always be skipped as parents."
    )
    force_skip_children: list[str] = Field(
        default_factory=list, description="List of resource types that should always be skipped as children."
    )
    included_providers: list[str] = Field(
        default_factory=_atlas_provider_only,
        description=f"List of providers that should be included. Defaults to {ATLAS_PROVIDER_NAME}",
    )
    emojii: str = Field(init=False, default_factory=choose_next_emoji)

    @model_validator(mode="after")
    def ensure_force_edges_are_valid(self) -> Self:
        # sourcery skip: raise-from-previous-error
        try:
            list(self.force_edges)
        except ValueError:
            raise ValueError(f"Force edges must be in the format of 'src:dest'. Got {self.force_edges}")
        return self

    @property
    def tree_label(self) -> str:
        return f"{self.emojii} {self.name}"

    @property
    def extra_edges(self) -> Iterable[tuple[str, str]]:
        for src_dest in self.force_edges:
            src, _, dest = src_dest.partition(":")
            yield src, dest

    def skip_edge(self, parent: str, child: str) -> SkipEdgeReason | None:
        if not self.is_root_edge(parent, child) and not self.include_non_root_edge(parent, child):
            return SkipEdgeReason.NOT_EXPLORABLE_EDGE
        if child in self.force_include_children:
            return None
        if parent in self.force_include_parents:
            return None
        if parent in self.force_skip_parents:
            return SkipEdgeReason.FORCE_SKIP_PARENT
        if child in self.force_skip_children:
            return SkipEdgeReason.FORCE_SKIP_CHILD
        if provider_name(parent) not in self.included_providers:
            return SkipEdgeReason.PROVIDER_PARENT_NOT_INCLUDED
        if provider_name(child) not in self.included_providers:
            return SkipEdgeReason.PROVIDER_CHILD_NOT_INCLUDED
        return None

    def is_root_edge(self, parent: str, child: str) -> bool:
        return parent in self.root_resource_types or child in self.root_resource_types

    def explore_edge(self, parent: str, child: str) -> bool:
        return child in self.explore_resource_types or parent in self.explore_resource_types

    def include_non_root_edge(self, parent: str, child: str) -> bool:
        return child in self.explore_resource_types or parent in self.explore_resource_types


class ModuleConfigs2(Entity):
    modules: list[ModuleConfig2] = Field(default_factory=list)
    skipped_resource_types: set[str] = Field(default_factory=set)
    include_deprecated_resource_types: bool = Field(default=False)

    @model_validator(mode="after")
    def add_resource_roots_as_skip_in_other_modules(self) -> Self:
        all_root_resources = set(flat_map(module.root_resource_types for module in self.modules))
        for module in self.modules:
            module.force_skip_parents.extend(
                parent for parent in all_root_resources if parent not in module.root_resource_types
            )
            module.force_skip_children.extend(
                child for child in all_root_resources if child not in module.root_resource_types
            )
        return self


def create_module_graph(
    shared_config: ModuleConfigs2, module_config: ModuleConfig2, global_graph: SimpleGraph
) -> SimpleGraph:
    graph = SimpleGraph()
    # global skipped resource types except for module root resource types should always be included
    skipped_resource_types = shared_config.skipped_resource_types - set(module_config.root_resource_types)

    for src, dest in global_graph.flat_edges():
        if src in skipped_resource_types or dest in skipped_resource_types:
            continue
        skip_reason = module_config.skip_edge(src, dest)
        if not skip_reason:
            graph.add_edge(src, dest)
    module_nodes = graph.all_nodes
    for node in module_config.root_resource_types:
        if node not in module_nodes:
            graph.add_root_node(node)
    for node in module_config.force_include_children:
        if node not in module_nodes:
            graph.add_root_node(node)
    for src, dest in module_config.extra_edges:
        graph.add_edge(src, dest)
    return graph


def module_tree(module_graph: SimpleGraph, module_config: ModuleConfig2, *, color_coder: ColorCoderABC) -> Tree:
    def tree_label(resource_type: str) -> str:
        color = color_coder.get_color(resource_type)
        return f"[{color}]{resource_type}[/]"

    tree = Tree(module_config.tree_label)
    resource_trees: dict[str, Tree] = {
        module_graph.ROOT_NODE: tree,
    }

    def prefer_root_src_over_nested(src_dest: tuple[str, str]) -> tuple[bool, bool, bool, str, str]:
        src, dest = src_dest
        is_module_root = any(root == src for root in module_config.root_resource_types)
        is_root = src == module_graph.ROOT_NODE
        is_child_of_other_resource_root = (
            any(src in module_graph.parent_child_edges.get(root, []) for root in module_config.root_resource_types)
            if is_module_root
            else False
        )

        return (not is_root, not is_module_root, is_child_of_other_resource_root, src, dest)

    # might be better to do a topological sort?
    for src, dest in sorted(
        module_graph.flat_edges(),
        key=prefer_root_src_over_nested,
    ):
        tree_src = resource_trees.get(src)
        if tree_src is None:
            tree_src = tree.add(tree_label(src))  # adding at root level
        resource_trees[src] = tree_src
        resource_trees[dest] = tree_src.add(tree_label(dest))
    return tree


def tf_module_grouping(
    config_path: Path = typer.Option(..., "-c", "--config", help="Path to the module grouping config file"),
):
    settings = TfExtSettings.from_env()
    shared_config = parse_model(config_path, t=ModuleConfigs2)
    example_parent_children = parse_dict(settings.example_graph_path)
    if not shared_config.include_deprecated_resource_types:
        info, _ = parse_atlas_schema_info(settings)
        shared_config.skipped_resource_types.update(info.deprecated_resource_types)
    graph = SimpleGraph(parent_child_edges=example_parent_children)
    out_dir = settings.module_grouping_dir(config_path.stem)
    for i, module in enumerate(shared_config.modules, start=1):
        module_graph = create_module_graph(shared_config, module, graph)
        write_graph(
            module_graph.to_dot_graph(module.name, keep_provider_name=True), out_dir, f"{i:02d}_{module.name}.png"
        )
        tree = module_tree(module_graph, module, color_coder=ColorCoderSimple(keep_provider_name=True))
        console.print_to_live(tree)
