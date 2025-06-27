import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Self

from model_lib import Entity, parse_list, parse_model
from pydantic import Field, RootModel, model_validator
import pydot
from rich.tree import Tree
import typer
from ask_shell import new_task, print_to_live
from zero_3rdparty.iter_utils import flat_map

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.settings import TfDepSettings
from atlas_init.tf_ext.tf_dep import FORCE_INTERNAL_NODES, SKIP_NODES, AtlasGraph, edge_src_dest

logger = logging.getLogger(__name__)


def default_modules() -> list[str]:
    return [
        "mongodbatlas_advanced_cluster",
        "mongodbatlas_cloud_provider_access_authorization",
        "mongodbatlas_project",
        "mongodbatlas_organization",
    ]


def default_skippped_module_resource_types() -> list[str]:
    return [
        "mongodbatlas_cluster",
        "mongodbatlas_flex_cluster",
        "mongodbatlas_stream_connection",
        "mongodbatlas_stream_instance",
        "mongodbatlas_stream_privatelink_endpoint",
        "mongodbatlas_stream_processor",
    ]


_emojii_list = [
    "1️⃣",
    "2️⃣",
    "3️⃣",
    "4️⃣",
    "5️⃣",
    "6️⃣",
    "7️⃣",
    "8️⃣",
    "9️⃣",
    "🔟",
]
_emoji_counter = 0


def choose_next_emoji() -> str:
    global _emoji_counter
    emoji = _emojii_list[_emoji_counter % len(_emojii_list)]
    _emoji_counter += 1
    return emoji


def default_allowed_multi_parents() -> set[str]:
    return {
        "mongodbatlas_project",
    }


class ModuleState(Entity):
    resource_types: set[str] = Field(default_factory=set, description="Set of resource types in the module.")


class ModuleConfig(Entity):
    name: str = Field(..., description="Name of the module.")
    root_resource_types: list[str] = Field(..., description="List of root resource types for the module.")
    force_include_children: list[str] = Field(
        default_factory=list, description="List of resource types that should always be included as children."
    )
    emojii: str = Field(init=False, default_factory=choose_next_emoji)
    allowed_multi_parents: set[str] = Field(
        default_factory=default_allowed_multi_parents,
        description="Set of parents that a child resource type can have in addition to the root_resource_type.",
    )
    allow_external_dependencies: bool = Field(
        default=False, description="Whether to allow external dependencies for the module."
    )
    extra_nested_resource_types: list[str] = Field(
        default_factory=list,
        description="List of additional nested resource types that should be included in the module.",
    )

    state: ModuleState = Field(default_factory=ModuleState, description="Internal state of the module.")

    @model_validator(mode="after")
    def update_state(self) -> Self:
        self.state.resource_types.update(self.root_resource_types)
        return self

    @property
    def tree_label(self) -> str:
        return f"{self.emojii} {self.name}"

    def include_child(self, child: str, atlas_graph: AtlasGraph) -> bool:
        if child in self.force_include_children or child in self.extra_nested_resource_types:
            self.state.resource_types.add(child)
            return True
        has_external_dependencies = len(atlas_graph.external_parents.get(child, [])) > 0
        if self.allow_external_dependencies and has_external_dependencies:
            has_external_dependencies = False
        is_a_parent = bool(atlas_graph.parent_child_edges.get(child))
        extra_parents = (
            set(atlas_graph.all_parents(child))
            - self.allowed_multi_parents
            - set(self.root_resource_types)
            - set(self.extra_nested_resource_types)
        )
        has_extra_parents = len(extra_parents) > 0
        if has_external_dependencies or is_a_parent or has_extra_parents:
            return False
        self.state.resource_types.add(child)
        return True


class ModuleConfigs(RootModel[dict[str, ModuleConfig]]):
    pass


default_module_configs = ModuleConfigs(
    root={
        "cloud_provider": ModuleConfig(
            name="Cloud Provider",
            root_resource_types=["mongodbatlas_cloud_provider_access_setup"],
            allow_external_dependencies=True,
            extra_nested_resource_types=["mongodbatlas_cloud_provider_access_authorization"],
            force_include_children=["mongodbatlas_encryption_at_rest"],
        ),
        "cluster": ModuleConfig(
            name="Cluster",
            root_resource_types=["mongodbatlas_advanced_cluster"],
        ),
        "project": ModuleConfig(
            name="Project",
            root_resource_types=["mongodbatlas_project"],
            force_include_children=[
                "mongodbatlas_project_ip_access_list"  # the external aws_vpc dependency is not really needed
            ],
        ),
        "organization": ModuleConfig(
            name="Organization",
            root_resource_types=["mongodbatlas_organization"],
        ),
        "cloud_backup_actions": ModuleConfig(
            name="Cloud Backup Actions",
            root_resource_types=[
                "mongodbatlas_cloud_backup_snapshot",
                "mongodbatlas_cloud_backup_snapshot_export_bucket",
            ],
        ),
    }
)


def tf_modules(
    skipped_module_resource_types: list[str] = typer.Option(
        ...,
        "-s",
        "--skip-resource-types",
        help="List of resource types to skip when creating module graphs",
        default_factory=default_skippped_module_resource_types,
        show_default=True,
    ),
):
    settings = TfDepSettings.from_env()
    atlas_graph = parse_atlas_graph(settings)
    output_dir = settings.static_root
    internal_color_coder = ColorCoder(atlas_graph, keep_provider_name=False)
    external_color_coder = ColorCoder(atlas_graph, keep_provider_name=True)
    with new_task("Write graphs"):
        internal_graph = create_internal_dependencies(atlas_graph)
        add_unused_nodes_to_graph(settings, atlas_graph, internal_color_coder, internal_graph)
        write_graph(internal_graph, output_dir, "atlas_internal.png")
        write_graph(create_external_dependencies(atlas_graph), output_dir, "atlas_external.png")
    with new_task("Write module graphs"):
        tree = Tree(
            "Module graphs",
        )
        used_resource_types: set[str] = set(
            skipped_module_resource_types
        )  # avoid the same resource_type in multiple module graphs
        for name, module_config in default_module_configs.root.items():
            internal_graph, external_graph = create_module_graphs(
                atlas_graph, module_config, used_resource_types=used_resource_types
            )
            module_tree = tree.add(module_config.tree_label)
            module_trees: dict[str, Tree] = {}

            def get_tree(resource_type: str) -> Tree | None:
                return next(
                    tree
                    for src, tree in module_trees.items()
                    if src.endswith(resource_type)  # provider name might be removed
                )

            def prefer_root_src_over_nested(src_dest: tuple[str, str]) -> tuple[bool, str, str]:
                src, dest = src_dest
                is_root = any(root.endswith(src) for root in module_config.root_resource_types)
                return (not is_root, src, dest)  # sort by whether src is a

            for src, dest in sorted(
                (edge_src_dest(edge) for edge in internal_graph.get_edge_list()), key=prefer_root_src_over_nested
            ):
                try:
                    tree_src = get_tree(src)
                except StopIteration:
                    resource_type = next(
                        root
                        for root in module_config.root_resource_types + module_config.extra_nested_resource_types
                        if root.endswith(src)  # provider name might be removed
                    )
                    tree_src = module_tree.add(resource_type)
                    module_trees[resource_type] = tree_src
                assert tree_src is not None, f"Source {src} not found in module tree"
                module_trees[dest] = tree_src.add(dest)
            write_graph(internal_graph, settings.static_root, f"{name}_internal.png")
            write_graph(external_graph, settings.static_root, f"{name}_external.png")
    print_to_live(tree)


def parse_atlas_graph(settings):
    atlas_graph = parse_model(settings.atlas_graph_path, t=AtlasGraph)
    atlas_graph.parent_child_edges["mongodbatlas_project"].add("mongodbatlas_auditing")
    return atlas_graph


def add_unused_nodes_to_graph(settings, atlas_graph, internal_color_coder, internal_graph):
    schema_resource_types: list[str] = parse_list(settings.schema_resource_types_path, format="yaml")
    all_nodes = atlas_graph.all_internal_nodes
    for resource_type in schema_resource_types:
        if resource_type not in all_nodes:
            internal_graph.add_node(internal_color_coder.create_node(resource_type, is_unused=True))


class NodeSkippedError(Exception):
    """Raised when a node is skipped during graph creation."""

    def __init__(self, resource_type: str):
        self.resource_type = resource_type
        super().__init__(f"Node skipped: {resource_type}. This is expected for some resource types.")


@dataclass
class ColorCoder:
    graph: AtlasGraph
    keep_provider_name: bool

    ATLAS_EXTERNAL_COLOR: str = "red"
    ATLAS_INTERNAL_COLOR: str = "green"
    ATLAS_INTERNAL_UNUSED_COLOR: str = "gray"
    EXTERNAL_COLOR: str = "purple"

    def create_node(self, resource_type: str, *, is_unused: bool = False) -> pydot.Node:
        if is_unused:
            color = self.ATLAS_INTERNAL_UNUSED_COLOR
        elif resource_type.startswith(ATLAS_PROVIDER_NAME):
            color = (
                "red"
                if resource_type in self.graph.all_external_nodes and resource_type not in FORCE_INTERNAL_NODES
                else "green"
            )
        else:
            color = self.EXTERNAL_COLOR
        return pydot.Node(self.node_name(resource_type), shape="box", style="filled", fillcolor=color)

    def node_name(self, resource_type: str) -> str:
        if resource_type in SKIP_NODES:
            raise NodeSkippedError(resource_type)
        return resource_type if self.keep_provider_name else remove_provider_name(resource_type)


def remove_provider_name(resource_type: str) -> str:
    return resource_type.split("_", 1)[-1]


def write_graph(dot_graph: pydot.Dot, out_path: Path, filename: str):
    out_path.mkdir(parents=True, exist_ok=True)
    dot_graph.write_png(out_path / filename)  # type: ignore


def as_nodes(edges: Iterable[tuple[str, str]]) -> set[str]:
    return set(flat_map((parent, child) for parent, child in edges))


def create_dot_graph(name: str, edges: Iterable[tuple[str, str]], *, color_coder: ColorCoder) -> pydot.Dot:
    edges = sorted(edges)
    graph = pydot.Dot(name, graph_type="graph")
    nodes = as_nodes(edges)
    for node in nodes:
        try:
            graph.add_node(color_coder.create_node(node))
        except NodeSkippedError:
            continue
    for src, dst in edges:
        try:
            graph.add_edge(pydot.Edge(color_coder.node_name(src), color_coder.node_name(dst), color="blue"))
        except NodeSkippedError:
            continue
    return graph


def create_module_graphs(
    atlas_graph: AtlasGraph, module_config: ModuleConfig, *, used_resource_types: set[str] | None = None
) -> tuple[pydot.Dot, pydot.Dot]:
    used_resource_types = used_resource_types or set()
    """Create two graphs: one for internal-only module dependencies and one for all module dependencies."""
    child_edges = [
        (root_resource_type, child)
        for root_resource_type in module_config.root_resource_types
        for child in atlas_graph.parent_child_edges[root_resource_type]
        if child not in used_resource_types
    ]
    child_edges.extend(
        (nested_resource_type, child)
        for nested_resource_type in module_config.extra_nested_resource_types
        for child in atlas_graph.parent_child_edges.get(nested_resource_type, [])
        if child not in used_resource_types
    )
    internal_only_edges = [
        (resource_type, child)
        for resource_type, child in child_edges
        if module_config.include_child(child, atlas_graph)
    ]
    module_name = module_config.name
    internal_graph = create_dot_graph(
        f"{module_name} Internal Only Dependencies",
        internal_only_edges,
        color_coder=ColorCoder(atlas_graph, keep_provider_name=False),
    )
    external_edges = [
        (parent, child)
        for child, parents in atlas_graph.external_parents.items()
        if child in child_edges
        for parent in parents
    ]
    external_graph = create_dot_graph(
        f"{module_name} External Dependencies",
        child_edges + external_edges,
        color_coder=ColorCoder(atlas_graph, keep_provider_name=True),
    )
    used_resource_types.update(module_config.root_resource_types)  # in case a root_resource_type doesn't have children
    used_resource_types |= as_nodes(internal_only_edges)
    return internal_graph, external_graph


def create_internal_dependencies(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph_name = "Atlas Internal Dependencies"
    return create_dot_graph(
        graph_name, atlas_graph.iterate_internal_edges(), color_coder=ColorCoder(atlas_graph, keep_provider_name=False)
    )


def create_external_dependencies(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph_name = "Atlas External Dependencies"
    return create_dot_graph(
        graph_name, atlas_graph.iterate_external_edges(), color_coder=ColorCoder(atlas_graph, keep_provider_name=True)
    )
