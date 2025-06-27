from __future__ import annotations
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar, Iterable

import pydot
import typer
from ask_shell import new_task, print_to_live
from model_lib import parse_list, parse_model
from rich.tree import Tree
from zero_3rdparty.iter_utils import flat_map

from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME
from atlas_init.tf_ext.models import ModuleConfig, ModuleConfigs
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
    ]


def default_module_configs() -> ModuleConfigs:
    return ModuleConfigs(
        root={
            "alerts": ModuleConfig(
                name="Alerts",
                root_resource_types=[
                    "mongodbatlas_alert_configuration",
                ],
            ),
            "auth": ModuleConfig(
                name="Authentication",
                root_resource_types=[
                    "mongodbatlas_api_key",
                    "mongodbatlas_custom_db_role",
                    "mongodbatlas_database_user",
                    "mongodbatlas_project_api_key",
                    "mongodbatlas_team",
                    "mongodbatlas_x509_authentication_database_user",
                ],
                force_include_children=[
                    "mongodbatlas_access_list_api_key",
                ],
            ),
            "ldap": ModuleConfig(
                name="LDAP",
                root_resource_types=[
                    "mongodbatlas_ldap_configuration",
                    "mongodbatlas_ldap_verify",
                ],
            ),
            "federated auth": ModuleConfig(
                name="Federated Authentication",
                root_resource_types=[
                    "mongodbatlas_federated_settings_identity_provider",
                ],
                force_include_children=[
                    "mongodbatlas_federated_settings_org_config",
                ],
            ),
            "federated DB": ModuleConfig(
                name="Federated Database",
                root_resource_types=[
                    "mongodbatlas_federated_database_instance",
                ],
            ),
            "network": ModuleConfig(
                name="Network",
                root_resource_types=[
                    "mongodbatlas_encryption_at_rest_private_endpoint",
                    "mongodbatlas_network_container",
                    "mongodbatlas_private_endpoint_regional_mode",
                    "mongodbatlas_privatelink_endpoint_service_data_federation_online_archive",
                    "mongodbatlas_privatelink_endpoint_service",
                    "mongodbatlas_privatelink_endpoint",
                    "mongodbatlas_stream_privatelink_endpoint",
                ],
                force_include_children=["mongodbatlas_network_peering"],
            ),
            "cloud_provider": ModuleConfig(
                name="Cloud Provider",
                root_resource_types=["mongodbatlas_cloud_provider_access_setup"],
                allow_external_dependencies=True,
                extra_nested_resource_types=["mongodbatlas_cloud_provider_access_authorization"],
                force_include_children=["mongodbatlas_encryption_at_rest"],
            ),
            "streams": ModuleConfig(
                name="Streams",
                root_resource_types=["mongodbatlas_stream_instance"],
                extra_nested_resource_types=["mongodbatlas_stream_connection"],
                force_include_children=["mongodbatlas_stream_processor"],
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
    with new_task("Write graphs"):
        color_coder_internal = color_coder(atlas_graph, keep_provider_name=False)
        internal_graph = create_internal_dependencies(atlas_graph, color_coder=color_coder_internal)
        add_unused_nodes_to_graph(settings, atlas_graph, color_coder_internal, internal_graph)
        write_graph(internal_graph, output_dir, "atlas_internal.png")
        write_graph(create_external_dependencies(atlas_graph), output_dir, "atlas_external.png")
    with new_task("Write module graphs"):
        modules = generate_module_graphs(skipped_module_resource_types, settings, atlas_graph)
    with new_task("Internal Graph with Module Numbers"):
        module_color_coder = ModuleColorCoder(
            atlas_graph,
            keep_provider_name=False,
            modules=modules,
        )
        internal_graph_with_numbers = create_internal_dependencies(atlas_graph, module_color_coder)
        add_unused_nodes_to_graph(settings, atlas_graph, module_color_coder, internal_graph_with_numbers)
        write_graph(internal_graph_with_numbers, settings.static_root, "atlas_internal_with_numbers.png")
    with new_task("Missing modules"):
        all_resources: list[str] = parse_list(settings.schema_resource_types_path, format="yaml")
        missing_resources = [
            resource_type
            for resource_type in all_resources
            if modules.module_emoji_prefix(resource_type) == ""
            and resource_type not in skipped_module_resource_types
            and resource_type not in atlas_graph.deprecated_resource_types
        ]
        logger.info(f"Missing modules: \n{'\n'.join(missing_resources)}")


def generate_module_graphs(skipped_module_resource_types, settings, atlas_graph):
    tree = Tree(
        "Module graphs",
    )
    used_resource_types: set[str] = set(
        skipped_module_resource_types
    )  # avoid the same resource_type in multiple module graphs
    modules = default_module_configs()
    for name, module_config in modules.root.items():
        internal_graph, external_graph = create_module_graphs(
            atlas_graph,
            module_config,
            color_coder_internal=color_coder(atlas_graph, keep_provider_name=False),
            color_coder_external=color_coder(atlas_graph, keep_provider_name=True),
            used_resource_types=used_resource_types,
        )
        module_tree = tree.add(module_config.tree_label)
        module_trees: dict[str, Tree] = {
            resource_type: module_tree.add(remove_provider_name(resource_type))
            for resource_type in module_config.root_resource_types
        }

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
                tree_src = module_tree.add(src)
                module_trees[resource_type] = tree_src
            assert tree_src is not None, f"Source {src} not found in module tree"
            module_trees[dest] = tree_src.add(dest)
        write_graph(internal_graph, settings.static_root, f"{name}_internal.png")
        write_graph(external_graph, settings.static_root, f"{name}_external.png")
    print_to_live(tree)
    return modules


def parse_atlas_graph(settings: TfDepSettings) -> AtlasGraph:
    atlas_graph = parse_model(settings.atlas_graph_path, t=AtlasGraph)
    deprecated_resources = parse_list(settings.schema_resource_types_deprecated_path, format="yaml")
    atlas_graph.deprecated_resource_types.update(deprecated_resources)
    atlas_graph.parent_child_edges["mongodbatlas_project"].add("mongodbatlas_auditing")
    atlas_graph.parent_child_edges["mongodbatlas_project"].add("mongodbatlas_custom_dns_configuration_cluster_aws")
    atlas_graph.parent_child_edges["mongodbatlas_advanced_cluster"].add("mongodbatlas_global_cluster_config")
    return atlas_graph


def add_unused_nodes_to_graph(
    settings: TfDepSettings, atlas_graph: AtlasGraph, color_coder: ColorCoder, internal_graph: pydot.Dot
):
    schema_resource_types: list[str] = parse_list(settings.schema_resource_types_path, format="yaml")
    all_nodes = atlas_graph.all_internal_nodes
    for resource_type in schema_resource_types:
        if resource_type not in all_nodes:
            internal_graph.add_node(color_coder.create_node(resource_type, is_unused=True))


class NodeSkippedError(Exception):
    """Raised when a node is skipped during graph creation."""

    def __init__(self, resource_type: str):
        self.resource_type = resource_type
        super().__init__(f"Node skipped: {resource_type}. This is expected for some resource types.")


@dataclass
class ColorCoder:
    graph: AtlasGraph
    keep_provider_name: bool

    ATLAS_EXTERNAL_COLOR: ClassVar[str] = "red"
    ATLAS_INTERNAL_COLOR: ClassVar[str] = "green"
    ATLAS_INTERNAL_UNUSED_COLOR: ClassVar[str] = "gray"
    ATLAS_DEPRECATED_COLOR: ClassVar[str] = "orange"
    EXTERNAL_COLOR: ClassVar[str] = "purple"

    def create_node(self, resource_type: str, *, is_unused: bool = False) -> pydot.Node:
        if resource_type in self.graph.deprecated_resource_types:
            color = self.ATLAS_DEPRECATED_COLOR
        elif is_unused:
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


def color_coder(atlas_graph: AtlasGraph, keep_provider_name: bool = False) -> ColorCoder:
    return ColorCoder(atlas_graph, keep_provider_name=keep_provider_name)


@dataclass
class ModuleColorCoder(ColorCoder):
    modules: ModuleConfigs

    def node_name(self, resource_type: str) -> str:
        if emoji_prefix := self.modules.module_emoji_prefix(resource_type):
            return f"{emoji_prefix} {super().node_name(resource_type)}"
        return super().node_name(resource_type)


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
    atlas_graph: AtlasGraph,
    module_config: ModuleConfig,
    *,
    color_coder_internal: ColorCoder,
    color_coder_external: ColorCoder,
    used_resource_types: set[str],
) -> tuple[pydot.Dot, pydot.Dot]:
    used_resource_types = used_resource_types or set()
    """Create two graphs: one for internal-only module dependencies and one for all module dependencies."""
    child_edges = [
        (root_resource_type, child)
        for root_resource_type in module_config.root_resource_types
        for child in atlas_graph.parent_child_edges.get(root_resource_type, [])
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
        color_coder=color_coder_internal,
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
        color_coder=color_coder_external,
    )
    used_resource_types.update(module_config.root_resource_types)  # in case a root_resource_type doesn't have children
    used_resource_types |= as_nodes(internal_only_edges)
    return internal_graph, external_graph


def create_internal_dependencies(atlas_graph: AtlasGraph, color_coder: ColorCoder) -> pydot.Dot:
    graph_name = "Atlas Internal Dependencies"
    return create_dot_graph(graph_name, atlas_graph.iterate_internal_edges(), color_coder=color_coder)


def create_external_dependencies(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph_name = "Atlas External Dependencies"
    return create_dot_graph(
        graph_name, atlas_graph.iterate_external_edges(), color_coder=color_coder(atlas_graph, keep_provider_name=True)
    )
