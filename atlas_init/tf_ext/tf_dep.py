import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from shutil import rmtree
from typing import Iterable, NamedTuple

import pydot
import typer
from ask_shell import AskShellSettings, ShellError, new_task, run_and_wait
from ask_shell._run import stop_runs_and_pool
from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from typer import Typer
from zero_3rdparty.iter_utils import flat_map

from atlas_init.settings.rich_utils import configure_logging
from atlas_init.tf_ext.args import REPO_PATH_ARG, SKIP_EXAMPLES_DIRS_OPTION
from atlas_init.tf_ext.paths import find_variable_resource_type_usages, find_variables, get_example_directories
from atlas_init.tf_ext.settings import TfDepSettings

logger = logging.getLogger(__name__)
v2_grand_parent_dirs = {
    "module_maintainer",
    "module_user",
    "migrate_cluster_to_advanced_cluster",
    "mongodbatlas_backup_compliance_policy",
}
v2_parent_dir = {"cluster_with_schedule"}
ATLAS_PROVIDER_NAME = "mongodbatlas"
MODULE_PREFIX = "module."
DATA_PREFIX = "data."


def is_v2_example_dir(example_dir: Path) -> bool:
    parent_dir = example_dir.parent.name
    grand_parent_dir = example_dir.parent.parent.name
    return parent_dir in v2_parent_dir or grand_parent_dir in v2_grand_parent_dirs


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


def tf_dep(
    repo_path: Path = REPO_PATH_ARG,
    skip_names: list[str] = SKIP_EXAMPLES_DIRS_OPTION,
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
    ask_shell_settings = AskShellSettings.from_env()
    rmtree(ask_shell_settings.run_logs)  # todo: fix upstream
    settings = TfDepSettings.from_env()
    output_dir = settings.static_root
    logger.info(f"Using output directory: {output_dir}")
    example_dirs = get_example_directories(repo_path, skip_names)
    with new_task("Find terraform graphs", total=len(example_dirs)) as task:
        atlas_graph = parse_graphs(example_dirs, task)
        for src, dsts in sorted(atlas_graph.parent_child_edges.items()):
            logger.info(f"{src} -> {', '.join(sorted(dsts))}")
    with new_task("Write graphs"):
        write_graph(create_internal_dependencies(atlas_graph), settings.static_root, "atlas_internal.png")
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


def write_graph(dot_graph: pydot.Dot, out_path: Path, filename: str):
    out_path.mkdir(parents=True, exist_ok=True)
    dot_graph.write_png(out_path / filename)  # type: ignore


def print_edges(graph: pydot.Dot):
    edges = graph.get_edges()
    for edge in edges:
        logger.info(f"{edge.get_source()} -> {edge.get_destination()}")


class ResourceParts(NamedTuple):
    resource_type: str
    resource_name: str

    @property
    def provider_name(self) -> str:
        return self.resource_type.split("_")[0]


class ResourceRef(BaseModel):
    full_ref: str

    def _resource_parts(self) -> ResourceParts:
        match self.full_ref.split("."):
            case [resource_type, resource_name] if "_" in resource_type:
                return ResourceParts(resource_type, resource_name)
            case [*_, resource_type, resource_name] if "_" in resource_type:
                return ResourceParts(resource_type, resource_name)
        raise ValueError(f"Invalid resource reference: {self.full_ref}")

    @property
    def provider_name(self) -> str:
        return self._resource_parts().provider_name

    @property
    def is_external(self) -> bool:
        return self.provider_name != ATLAS_PROVIDER_NAME

    @property
    def is_atlas_resource(self) -> bool:
        return not self.is_module and not self.is_data and self.provider_name == ATLAS_PROVIDER_NAME

    @property
    def is_module(self) -> bool:
        return self.full_ref.startswith(MODULE_PREFIX)

    @property
    def is_data(self) -> bool:
        return self.full_ref.startswith(DATA_PREFIX)

    @property
    def resource_type(self) -> str:
        return self._resource_parts().resource_type


class EdgeParsed(BaseModel):
    parent: ResourceRef
    child: ResourceRef

    @classmethod
    def from_edge(cls, edge: pydot.Edge) -> "EdgeParsed":
        return cls(
            # edges shows from child --> parent, so we reverse the order
            parent=ResourceRef(full_ref=edge_plain(edge.get_destination())),
            child=ResourceRef(full_ref=edge_plain(edge.get_source())),
        )

    @property
    def has_module_edge(self) -> bool:
        return self.parent.is_module or self.child.is_module

    @property
    def has_data_edge(self) -> bool:
        return self.parent.is_data or self.child.is_data

    @property
    def is_resource_edge(self) -> bool:
        return not self.has_module_edge and not self.has_data_edge

    @property
    def is_external_to_internal_edge(self) -> bool:
        return self.parent.is_external and self.child.is_atlas_resource

    @property
    def is_internal_atlas_edge(self) -> bool:
        return self.parent.is_atlas_resource and self.child.is_atlas_resource


def edge_plain(edge_endpoint: pydot.EdgeEndpoint) -> str:
    return str(edge_endpoint).strip('"').strip()


VARIABLE_RESOURCE_MAPPING: dict[str, str] = {
    "org_id": "mongodbatlas_organization",
    "project_id": "mongodbatlas_project",
    "cluster_name": "mongodbatlas_advanced_cluster",
}
SKIP_NODES: set[str] = {"mongodbatlas_cluster"}


def skip_variable_edge(src: str, dst: str) -> bool:
    # sourcery skip: assign-if-exp, boolean-if-exp-identity, reintroduce-else, remove-unnecessary-cast
    if src == dst:
        return True
    if src == "mongodbatlas_advanced_cluster" and "_cluster" in dst:
        return True
    return False


@dataclass
class AtlasGraph:
    # atlas_resource_type -> set[atlas_resource_type]
    parent_child_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    # atlas_resource_type -> set[exteranl_resource_type]
    external_parents: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def all_internal_nodes(self) -> set[str]:
        return set(flat_map([src] + list(dsts) for src, dsts in self.parent_child_edges.items()))

    def iterate_internal_edges(self) -> Iterable[tuple[str, str]]:
        for parent, children in self.parent_child_edges.items():
            for child in children:
                yield parent, child

    @property
    def all_external_nodes(self) -> set[str]:
        return set(flat_map([src] + list(dsts) for src, dsts in self.external_parents.items()))

    def iterate_external_edges(self) -> Iterable[tuple[str, str]]:
        for child, parents in self.external_parents.items():
            for parent in parents:
                yield parent, child

    def add_edges(self, edges: list[pydot.Edge]):
        for edge in edges:
            parsed = EdgeParsed.from_edge(edge)
            parent = parsed.parent
            child = parsed.child
            if parsed.is_internal_atlas_edge:
                self.parent_child_edges[parent.resource_type].add(child.resource_type)
                # edges shows from child --> parent, so we reverse the order
            elif parsed.is_external_to_internal_edge:
                if parent.provider_name in {"random", "cedar"}:
                    continue  # skip random provider edges
                self.external_parents[child.resource_type].add(parent.resource_type)

    def add_variable_edges(self, example_dir: Path) -> None:
        """Use the variables to find the resource dependencies."""
        if not (variables := find_variables(example_dir / "variables.tf")):
            return
        usages = find_variable_resource_type_usages(set(variables), example_dir)
        for variable, resource_types in usages.items():
            if parent_type := VARIABLE_RESOURCE_MAPPING.get(variable):
                for child_type in resource_types:
                    if skip_variable_edge(parent_type, child_type):
                        continue
                    if child_type.startswith(ATLAS_PROVIDER_NAME):
                        logger.info(f"Adding variable edge: {parent_type} -> {child_type}")
                        self.parent_child_edges[parent_type].add(child_type)


def parse_graphs(example_dirs: list[Path], task: new_task, max_workers: int = 16, max_dirs: int = 9999) -> AtlasGraph:
    atlas_graph = AtlasGraph()
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(parse_graph, example_dir): example_dir
            for i, example_dir in enumerate(example_dirs)
            if i < max_dirs
        }
        graphs = {}
        for future in futures:
            try:
                example_dir, graph_output = future.result()
            except ShellError as e:
                logger.error(f"Error parsing graph for {futures[future]}: {e}")
                continue
            except KeyboardInterrupt:
                logger.error("KeyboardInterrupt received, stopping graph parsing.")
                stop_runs_and_pool("KeyboardInterrupt", immediate=True)
                break
            try:
                graph = graphs[example_dir] = parse_graph_output(example_dir, graph_output)
            except GraphParseError as e:
                logger.error(e)
                continue
            atlas_graph.add_edges(graph.get_edges())
            atlas_graph.add_variable_edges(example_dir)
            task.update(advance=1)
    return atlas_graph


class GraphParseError(Exception):
    def __init__(self, example_dir: Path, message: str):
        self.example_dir = example_dir
        super().__init__(f"Failed to parse graph for {example_dir}: {message}")


def parse_graph_output(example_dir: Path, graph_output: str, verbose: bool = False) -> pydot.Dot:
    assert graph_output, f"Graph output is empty for {example_dir}"
    dots = pydot.graph_from_dot_data(graph_output)  # not thread safe, so we use the main thread here instead
    if not dots:
        raise GraphParseError(example_dir, f"No graphs found in the output:\n{graph_output}")
    assert len(dots) == 1, f"Expected one graph for {example_dir}, got {len(dots)}"
    graph = dots[0]
    edges = graph.get_edges()
    if not edges:
        logger.info(f"No edges found in graph for {example_dir}")
    if verbose:
        print_edges(graph)
    return graph


class EmptyGraphOutputError(Exception):
    """Raised when the graph output is empty."""

    def __init__(self, example_dir: Path):
        self.example_dir = example_dir
        super().__init__(f"Graph output is empty for {example_dir}")


@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(1),
    retry=retry_if_exception_type(EmptyGraphOutputError),
    reraise=True,
)
def parse_graph(example_dir: Path) -> tuple[Path, str]:
    env_vars = {
        "MONGODB_ATLAS_PREVIEW_PROVIDER_V2_ADVANCED_CLUSTER": "true" if is_v2_example_dir(example_dir) else "false",
    }
    lock_file = example_dir / ".terraform.lock.hcl"
    if not lock_file.exists():
        run_and_wait("terraform init", cwd=example_dir, env=env_vars)
    run = run_and_wait("terraform graph", cwd=example_dir, env=env_vars)
    if graph_output := run.stdout_one_line:
        return example_dir, graph_output
    raise EmptyGraphOutputError(example_dir)


def create_internal_dependencies(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph_name = "Atlas Internal Dependencies"
    return create_dot_graph(graph_name, atlas_graph.iterate_internal_edges(), keep_provider_name=False)


def create_external_dependencies(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph_name = "Atlas External Dependencies"
    return create_dot_graph(graph_name, atlas_graph.iterate_external_edges(), keep_provider_name=True)


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
        keep_provider_name=False,
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
        keep_provider_name=True,
    )
    used_resource_types.add(module_resource_type)
    used_resource_types |= as_nodes(child_edges)
    return internal_graph, external_graph


def create_dot_graph(name: str, edges: Iterable[tuple[str, str]], *, keep_provider_name: bool = False) -> pydot.Dot:
    def node_name(full_name: str) -> str:
        return full_name if keep_provider_name else full_name.split("_", 1)[-1]

    edges = sorted(edges)
    graph = pydot.Dot(name, graph_type="graph", bgcolor="yellow")
    nodes = as_nodes(edges)
    for node in nodes:
        graph.add_node(pydot.Node(node_name(node), shape="box", style="filled", fillcolor="lightgrey"))
    for src, dst in edges:
        graph.add_edge(pydot.Edge(node_name(src), node_name(dst), color="blue"))
    return graph


def as_nodes(edges: Iterable[tuple[str, str]]) -> set[str]:
    return set(flat_map((parent, child) for parent, child in edges))


def typer_main():
    app = Typer()
    app.command()(tf_dep)
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
