import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from model_lib import parse_model
import pydot
import typer
from ask_shell import new_task
from zero_3rdparty.iter_utils import flat_map

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.settings import TfDepSettings
from atlas_init.tf_ext.tf_dep import FORCE_INTERNAL_NODES, SKIP_NODES, AtlasGraph

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


def tf_modules(
    modules: list[str] = typer.Option(
        ...,
        "-m",
        "--modules",
        help="List of module names to create graphs for. Should start with the deepest in the hierarchy, for example cluster, project, organization.",
        default_factory=default_modules,
        show_default=True,
    ),
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
    atlas_graph = parse_model(settings.atlas_graph_path, t=AtlasGraph)
    output_dir = settings.static_root
    with new_task("Write graphs"):
        write_graph(create_internal_dependencies(atlas_graph), output_dir, "atlas_internal.png")
        write_graph(create_external_dependencies(atlas_graph), output_dir, "atlas_external.png")
    with new_task("Write module graphs"):
        used_resource_types: set[str] = set(
            skipped_module_resource_types
        )  # avoid the same resource_type in multiple module graphs
        for module in modules:
            internal_graph, external_graph = create_module_graphs(
                atlas_graph, module, used_resource_types=used_resource_types
            )
            write_graph(internal_graph, settings.static_root, f"{module}_internal.png")
            write_graph(external_graph, settings.static_root, f"{module}_external.png")


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
    EXTERNAL_COLOR: str = "purple"

    def create_node(self, resource_type: str) -> pydot.Node:
        if resource_type.startswith(ATLAS_PROVIDER_NAME):
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
        return resource_type if self.keep_provider_name else resource_type.split("_", 1)[-1]


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
    atlas_graph: AtlasGraph, module_resource_type: str, *, used_resource_types: set[str] | None = None
) -> tuple[pydot.Dot, pydot.Dot]:
    used_resource_types = used_resource_types or set()
    """Create two graphs: one for internal-only module dependencies and one for all module dependencies."""
    internal_children = [
        child for child in atlas_graph.parent_child_edges[module_resource_type] if child not in used_resource_types
    ]
    child_edges = [(module_resource_type, child) for child in internal_children]
    internal_only_edges = [
        (module_resource_type, child) for child in internal_children if child not in atlas_graph.external_parents
    ]
    internal_graph = create_dot_graph(
        f"{module_resource_type} Internal Only Dependencies",
        internal_only_edges,
        color_coder=ColorCoder(atlas_graph, keep_provider_name=False),
    )
    external_edges = [
        (parent, child)
        for child, parents in atlas_graph.external_parents.items()
        if child in internal_children
        for parent in parents
    ]
    external_graph = create_dot_graph(
        f"{module_resource_type} External Dependencies",
        child_edges + external_edges,
        color_coder=ColorCoder(atlas_graph, keep_provider_name=True),
    )
    used_resource_types.add(module_resource_type)
    used_resource_types |= as_nodes(child_edges)
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
