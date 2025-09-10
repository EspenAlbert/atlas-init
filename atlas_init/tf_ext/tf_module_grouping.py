from pathlib import Path
from typing import Self

from ask_shell import print_to_live
from model_lib import Entity, parse_dict, parse_model
from pydantic import Field, model_validator
from rich.tree import Tree
import typer

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.models import choose_next_emoji
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.tf_mod_gen_provider import parse_atlas_schema_info
from atlas_init.tf_ext.tf_modules import write_graph
from atlas_init.tf_ext.tf_resource_usage import SimpleGraph


def _atlas_provider_only() -> list[str]:
    return [ATLAS_PROVIDER_NAME]


class ModuleConfig2(Entity):
    name: str = Field(..., description="Name of the module.")
    root_resource_types: list[str] = Field(..., description="List of root resource types for the module.")
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

    @property
    def tree_label(self) -> str:
        return f"{self.emojii} {self.name}"

    def include_edge(self, parent: str, child: str) -> bool:
        parent_is_module_root = parent in self.root_resource_types
        child_is_module_root = child in self.root_resource_types
        if not parent_is_module_root and not child_is_module_root:
            return False
        if child in self.force_include_children:
            return True
        if parent in self.force_include_parents:
            return True
        skipped = parent in self.force_skip_parents or child in self.force_skip_parents
        provider_skipped = (
            provider_name(parent) not in self.included_providers or provider_name(child) not in self.included_providers
        )
        return not skipped and not provider_skipped


class ModuleConfigs2(Entity):
    modules: list[ModuleConfig2] = Field(default_factory=list)
    skipped_resource_types: set[str] = Field(default_factory=set)
    include_deprecated_resource_types: bool = Field(default=False)

    @model_validator(mode="after")
    def add_resource_roots_as_force_skip_parents(self) -> Self:
        used_resource_roots = set()
        for module in self.modules:
            module.force_skip_parents.extend(
                parent for parent in used_resource_roots if parent not in module.root_resource_types
            )
            used_resource_roots.update(module.root_resource_types)
        return self


def provider_name(resource_type: str) -> str:
    return resource_type.split("_", maxsplit=1)[0]


def create_module_graph(
    shared_config: ModuleConfigs2, module_config: ModuleConfig2, global_graph: SimpleGraph
) -> SimpleGraph:
    graph = SimpleGraph()
    skipped_resource_types = shared_config.skipped_resource_types | set(module_config.force_skip_children)

    for src, dest in global_graph.flat_edges():
        if src in skipped_resource_types or dest in skipped_resource_types:
            continue
        if module_config.include_edge(src, dest):
            graph.add_edge(src, dest)
    module_nodes = graph.all_nodes
    for node in module_config.root_resource_types:
        if node not in module_nodes:
            graph.add_root_node(node)
    for node in module_config.force_include_children:
        if node not in module_nodes:
            graph.add_root_node(node)
    return graph


def module_tree(module_graph: SimpleGraph, module_config: ModuleConfig2) -> Tree:
    tree = Tree(module_config.tree_label)
    resource_trees: dict[str, Tree] = {
        module_graph.ROOT_NODE: tree,
    }

    def prefer_root_src_over_nested(src_dest: tuple[str, str]) -> tuple[bool, bool, bool, str, str]:
        src, dest = src_dest
        is_module_root = any(root == src for root in module_config.root_resource_types)
        is_root = src == module_graph.ROOT_NODE
        is_child_of_other_resource_root = (
            False
            if not is_module_root
            else any(src in module_graph.parent_child_edges.get(root, []) for root in module_config.root_resource_types)
        )

        return (not is_root, not is_module_root, is_child_of_other_resource_root, src, dest)

    # might be better to do a topological sort?
    for src, dest in sorted(
        module_graph.flat_edges(),
        key=prefer_root_src_over_nested,
    ):
        tree_src = resource_trees.get(src)
        if tree_src is None:
            tree_src = tree.add(src)  # adding at root level
        resource_trees[src] = tree_src
        resource_trees[dest] = tree_src.add(dest)
    return tree


def tf_module_grouping(
    config_path: Path = typer.Option(..., "-c", "--config", help="Path to the module grouping config file"),
):
    settings = TfExtSettings.from_env()
    config = parse_model(config_path, t=ModuleConfigs2)
    example_parent_children = parse_dict(settings.example_graph_path)
    if not config.include_deprecated_resource_types:
        info, _ = parse_atlas_schema_info(settings)
        config.skipped_resource_types.update(info.deprecated_resource_types)
    graph = SimpleGraph(parent_child_edges=example_parent_children)
    out_dir = settings.module_grouping_dir(config_path.stem)
    for i, module in enumerate(config.modules, start=1):
        module_graph = create_module_graph(config, module, graph)
        write_graph(
            module_graph.to_dot_graph(module.name, keep_provider_name=True), out_dir, f"{i:02d}_{module.name}.png"
        )
        tree = module_tree(module_graph, module)
        print_to_live(tree)
