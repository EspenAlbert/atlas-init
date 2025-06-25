from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
import logging
from pathlib import Path
from typing import Iterable, NamedTuple

from pydantic import BaseModel
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from typer import Typer
import typer
import pydot

from ask_shell import ShellError, new_task, run_and_wait
from zero_3rdparty.iter_utils import flat_map
from atlas_init.cli_tf.hcl.modifier2 import safe_parse, variable_reader, variable_usages
from atlas_init.settings.rich_utils import configure_logging


logger = logging.getLogger(__name__)
app = Typer()
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


@app.command()
def tf_dep(
    repo_path: Path = typer.Argument(),
    skip_names: list[str] = typer.Option([], "-s", "--skip-names", help="Skip example directories with these names"),
):
    example_dirs = find_example_dirs(repo_path)
    logger.info(f"Found {len(example_dirs)} example directories in {repo_path}")
    if skip_names:
        len_before = len(example_dirs)
        example_dirs = [d for d in example_dirs if not any(skip_name == d.name for skip_name in skip_names)]
        logger.info(f"Skipped {len_before - len(example_dirs)} example directories with names: {skip_names}")
    with new_task("Find terraform graphs", total=len(example_dirs)) as task:
        atlas_graph = parse_graphs(example_dirs, task)
        for src, dsts in sorted(atlas_graph.parent_child_edges.items()):
            logger.info(f"{src} -> {', '.join(sorted(dsts))}")
        dot_graph = create_dot_graph(atlas_graph)
        dot_graph.write_png("atlas-dependencies.png")  # type: ignore


def find_example_dirs(repo_path: Path) -> list[Path]:
    example_dirs: set[Path] = {
        tf_file.parent for tf_file in (repo_path / "examples").rglob("*.tf") if ".terraform" not in tf_file.parts
    }
    return sorted(example_dirs)


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
    parent_child_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))
    external_parent_child_edges: dict[str, set[str]] = field(default_factory=lambda: defaultdict(set))

    @property
    def all_nodes(self) -> set[str]:
        return set(flat_map([src] + list(dsts) for src, dsts in self.parent_child_edges.items()))

    def iterate_edges(self) -> Iterable[tuple[str, str]]:
        for src, dsts in self.parent_child_edges.items():
            for dst in dsts:
                yield src, dst

    def add_edges(self, edges: list[pydot.Edge]):
        for edge in edges:
            parsed = EdgeParsed.from_edge(edge)
            if parsed.is_internal_atlas_edge():
                self.parent_child_edges[parsed.parent.resource_type].add(parsed.child.resource_type)
                # edges shows from child --> parent, so we reverse the order
            else:
                logger.warning(f"Skipping non-Atlas edge: {edge.get_source()} -> {edge.get_destination()}")

    def add_variable_edges(self, example_dir: Path) -> None:
        """Use the variables to find the resource dependencies."""
        if not (variables := find_variables(example_dir / "variables.tf")):
            return
        usages = find_variable_resource_type_usages(variables, example_dir)
        for variable, resource_types in usages.items():
            if parent_type := VARIABLE_RESOURCE_MAPPING.get(variable):
                for child_type in resource_types:
                    if skip_variable_edge(parent_type, child_type):
                        continue
                    if child_type.startswith(ATLAS_PROVIDER_NAME):
                        logger.info(f"Adding variable edge: {parent_type} -> {child_type}")
                        self.parent_child_edges[parent_type].add(child_type)


def find_variables(variables_tf: Path) -> set[str]:
    tree = safe_parse(variables_tf)
    if not tree:
        logger.warning(f"Failed to parse {variables_tf}")
        return set()
    return variable_reader(tree)


def find_variable_resource_type_usages(variables: set[str], example_dir: Path) -> dict[str, set[str]]:
    usages = defaultdict(set)
    for path in example_dir.glob("*.tf"):
        tree = safe_parse(path)
        if not tree:
            logger.warning(f"Failed to parse {path}")
            continue
        path_usages = variable_usages(variables, tree)
        for variable, resources in path_usages.items():
            usages[variable].update(resources)
    return usages


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
    retry=retry_if_exception_type(),
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


def create_dot_graph(atlas_graph: AtlasGraph) -> pydot.Dot:
    graph = pydot.Dot("Atlas Dependencies", graph_type="graph", bgcolor="yellow")
    for node in atlas_graph.all_nodes:
        graph.add_node(pydot.Node(node, shape="box", style="filled", fillcolor="lightgrey"))
    for src, dst in atlas_graph.iterate_edges():
        graph.add_edge(pydot.Edge(src, dst, color="blue"))
    return graph


def typer_main():
    configure_logging(app)
    app()


if __name__ == "__main__":
    typer_main()
