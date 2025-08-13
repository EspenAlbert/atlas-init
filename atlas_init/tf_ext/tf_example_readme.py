from collections import defaultdict
from contextlib import suppress
from functools import total_ordering
import logging
from pathlib import Path
from typing import ClassVar, Iterable, Protocol, TypeAlias
from ask_shell import new_task
from ask_shell.rich_live import get_live_console
from model_lib import Entity, parse_dict
from pydantic import Field, model_validator
import pydot
from rich.tree import Tree
import typer

from atlas_init.settings.rich_utils import tree_text
from atlas_init.tf_ext.gen_readme import ReadmeMarkers, generate_and_write_readme
from atlas_init.tf_ext.models import EmojiCounter
from atlas_init.tf_ext.models_module import README_FILENAME
from atlas_init.tf_ext.tf_dep import EdgeParsed, ResourceRef, node_plain, parse_graph, parse_graph_output, parse_graphs

logger = logging.getLogger(__name__)
MODULES_JSON_RELATIVE_PATH = ".terraform/modules/modules.json"


def tf_example_readme(
    example_path: Path = typer.Option(
        ..., "-e", "--example-path", help="Path to the example directory", default_factory=Path.cwd
    ),
    skip_module_keys: list[str] = typer.Option(
        ..., "-s", "--skip-module-keys", help="List of module keys to skip", default_factory=list
    ),
):
    with new_task("parse example graph"):
        _, example_graph_output = parse_graph(example_path)  # ensures init is called
        example_graph_dot = parse_graph_output(example_path, example_graph_output)
        example_graph = ResourceGraph.from_graph(example_graph_dot)
    with new_task("parse module graphs") as task:
        modules_config = parse_modules_json(example_path)
        modules = modules_config.modules_included(skip_keys=skip_module_keys)
        assert modules, f"no modules found in {example_path} that are not in {skip_module_keys} (skip_module_keys)"
        module_paths = [example_path / module.rel_path for module in modules]
        if not_found_paths := [path for path in module_paths if not path.exists()]:
            raise ValueError(f"module paths not found: {not_found_paths}")
        module_graphs: dict[Path, ResourceGraph] = {}

        def on_graph(example_dir: Path, graph: pydot.Dot):
            module_graphs[example_dir] = ResourceGraph.from_graph(graph)

        parse_graphs(on_graph, module_paths, task)
    with new_task("create example module graph"):
        # a graph when all resources in a module are treated as a single node.
        emoji_counter = EmojiCounter()

        def as_module_edge(parent: ResourceRef, child: ResourceRef) -> bool | ParentChild:
            if not child.is_module:
                return False
            parent_module = as_module_name(parent)
            new_parent = as_module_ref(parent)
            if parent_module:
                parent_emoji = emoji_counter.get_emoji(parent_module)
                new_parent = ResourceRef(full_ref=f"{parent_emoji} {parent_module}")
            child_module = as_module_name(child)
            new_child = as_module_ref(child)
            if child_module:
                child_emoji = emoji_counter.get_emoji(child_module)
                new_child = ResourceRef(full_ref=f"{child_emoji} {child_module}")
            return new_parent, new_child

        modules_graph = create_subgraph(example_graph, as_module_edge)
    with new_task(f"update {README_FILENAME}"):
        modules_section = []
        modules_trees_texts = []
        module_dirs_used: set[Path] = set()

        def add_module_tree(module_dir: Path):
            # trees are only once per module, not per module instance
            if module_dir in module_dirs_used:
                return
            module_dirs_used.add(module_dir)
            module_graph = module_graphs[module_dir]
            module_config = modules_config.get_by_path(module_dir)
            emojis = ", ".join(emoji_counter.get_emoji(key) for key in module_config.keys)
            tree = module_graph.to_tree(f"{module_dir.name} ({emojis})", include_orphans=True)
            get_live_console().print(tree)
            modules_trees_texts.append(tree_text(tree))

        for ref in modules_graph.sorted_parents():
            if not ref.is_module:
                continue
            module_config = modules_config.get_by_key(ref.module_name)
            add_module_tree(module_config.absolute_path(example_path))
        for module_dir in module_graphs:  # process the modules not used as parents
            add_module_tree(module_dir)
        modules_section.extend(
            [
                "## Modules",
                "",
                "### Tree",
                "",
                "```",
                "\n".join(modules_trees_texts),
                "```",
            ]
        )
        # modules_section.append(f"### Graph\n\n```{as_mermaid(modules_graph)}")
        generators = ReadmeMarkers.readme_generators()
        generators.insert(1, (ReadmeMarkers.MODULES, lambda _: "\n".join(modules_section)))
        generate_and_write_readme(
            example_path,
            generators=generators,
        )
    # dot_graph = parse_graph_output(example_path, graph_output)
    # full_graph_path = out_dir / "full_graph.dot"
    # ensure_parents_write_text(full_graph_path, dot_graph.to_string())
    # logger.info(f"writing to {full_graph_path} full graph")
    # write_graph(dot_graph, out_dir, "full_graph.png")
    # for sub_graph in dot_graph.get_subgraph_list():
    #     dot_content = sub_graph.to_string()
    #     name = sub_graph.get_attributes()["label"].replace(".", "_").strip('"')
    #     path = out_dir / f"{name}.dot"
    #     ensure_parents_write_text(path, dot_content)
    #     logger.info(f"writing to {path} {name} graph")
    # get_live_console().print(dot_graph)


def as_module_name(ref: ResourceRef) -> str:
    if ref.is_module:
        return ref.module_name
    return ""


def as_module_ref(ref: ResourceRef) -> ResourceRef:
    if name := as_module_name(ref):
        return ResourceRef(full_ref=f"module.{name}")
    return ref


class _RootModuleIgnored(Exception):
    pass


ParentChild: TypeAlias = tuple[ResourceRef, ResourceRef]


class ResourceGraph(Entity):
    IGNORED_ORPHANS: ClassVar[set[str]] = {"node"}  # some extra output from `terraform graph` command
    parent_children: dict[ResourceRef, set[ResourceRef]] = Field(default_factory=lambda: defaultdict(set))
    children_parents: dict[ResourceRef, set[ResourceRef]] = Field(default_factory=lambda: defaultdict(set))
    orphans: set[ResourceRef] = Field(default_factory=set)

    @classmethod
    def from_graph(cls, graph: pydot.Dot) -> "ResourceGraph":
        resource_graph = cls()
        resource_graph.add_edges(graph.get_edges())
        for orphan in graph.get_node_list():
            name = node_plain(orphan)
            if name in cls.IGNORED_ORPHANS:
                continue
            ref = ResourceRef(full_ref=name)
            resource_graph.add_orphan_if_not_found(ref)
        return resource_graph

    def add_orphan_if_not_found(self, orphan: ResourceRef):
        if orphan not in self.parent_children and orphan not in self.children_parents:
            self.orphans.add(orphan)

    def add_edges(self, edges: list[pydot.Edge]):
        for edge in edges:
            parsed = EdgeParsed.from_edge(edge)
            parent = parsed.parent
            child = parsed.child
            self.add_edge(parent, child)

    def add_edge(self, parent: ResourceRef, child: ResourceRef):
        self.parent_children[parent].add(child)
        self.children_parents[child].add(parent)

    def all_edges(self) -> list[ParentChild]:
        return [(parent, child) for parent in self.parent_children for child in self.parent_children[parent]]

    @property
    def all_parents(self) -> set[ResourceRef]:
        return set(self.parent_children.keys())

    def sorted_parents(self) -> Iterable[ResourceRef]:
        used_parents = set()
        remaining_parents = self.all_parents

        def next_parent() -> ResourceRef | None:
            candidates = [parent for parent in remaining_parents if not self.children_parents[parent] - used_parents]
            return min(candidates) if candidates else None

        while remaining_parents:
            parent = next_parent()
            if parent is None:
                break
            used_parents.add(parent)
            yield parent
            remaining_parents.remove(parent)

    def to_tree(self, example_dir_name: str, include_orphans: bool = False) -> Tree:
        root = Tree(example_dir_name)
        trees: dict[ResourceRef, Tree] = {}

        for parent in self.sorted_parents():
            parent_tree = trees.setdefault(parent, Tree(parent.full_ref))
            for child_ref in sorted(self.parent_children[parent]):
                child_tree = trees.setdefault(child_ref, Tree(child_ref.full_ref))
                parent_tree.add(child_tree)
            if not self.children_parents[parent]:
                root.add(parent_tree)
        if include_orphans:
            for orphan in self.orphans:
                if orphan not in trees:
                    root.add(Tree(orphan.full_ref))
        return root


def as_mermaid(graph: ResourceGraph) -> str:
    raise NotImplementedError("not implemented")


class EdgeFilter(Protocol):
    def __call__(self, parent: ResourceRef, child: ResourceRef) -> bool | ParentChild: ...


def create_subgraph(graph: ResourceGraph, edge_filter: EdgeFilter) -> ResourceGraph:
    subgraph = ResourceGraph()
    for parent in graph.sorted_parents():
        for child in graph.parent_children[parent]:
            filter_response = edge_filter(parent, child)
            match filter_response:
                case True:
                    subgraph.add_edge(parent, child)
                case False:
                    continue
                case (parent, child):
                    subgraph.add_edge(parent, child)
    return subgraph


@total_ordering
class ModuleExampleConfig(Entity):
    keys: list[str]
    rel_path: str = Field(alias="Dir", description="Relative path to the module example")
    source: str = Field(
        alias="Source",
        description="Source of the module, for example: registry.terraform.io/terraform-aws-modules/vpc/aws",
    )
    version: str = Field(
        alias="Version", description="Version of the module example, unset for local modules", default=""
    )

    @model_validator(mode="before")
    @classmethod
    def move_key(cls, v: dict):
        key = v.pop("Key", None)
        if key:
            v["keys"] = [key]
        if v.get("Dir", "") == ".":
            raise _RootModuleIgnored()
        return v

    @model_validator(mode="after")
    def validate_keys(self):
        if not self.keys:
            raise ValueError("keys is required")
        return self

    @property
    def key(self) -> str:
        return ",".join(sorted(self.keys))

    def absolute_path(self, example_path: Path) -> Path:
        path = example_path / self.rel_path
        if not path.exists():
            raise ValueError(f"module path not found for {self.key}: {path}")
        return path

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, ModuleExampleConfig):
            raise TypeError(f"cannot compare {type(self)} with {type(other)}")
        return self.key < other.key


class ModuleExampleConfigs(Entity):
    example_path: Path
    modules: dict[str, ModuleExampleConfig] = Field(default_factory=dict)

    def get_by_path(self, module_dir: Path) -> ModuleExampleConfig:
        for config in self.modules.values():
            if config.absolute_path(self.example_path) == module_dir:
                return config
        raise ValueError(f"module not found for {module_dir}")

    def get_by_key(self, key: str) -> ModuleExampleConfig:
        return self.modules[key]

    def modules_included(self, *, skip_keys: list[str]) -> list[ModuleExampleConfig]:
        return [config for config in self.modules.values() if all(key not in skip_keys for key in config.keys)]

    def add_module(self, config: ModuleExampleConfig):
        key = config.keys[0]
        assert len(config.keys) == 1, "only one key can be added at a time"
        source = config.source
        existing_config = next(
            (existing_config for existing_config in self.modules.values() if source == existing_config.source),
            None,
        )
        if existing_config:
            existing_config.keys.append(key)
            existing_config.keys.sort()
            self.modules[key] = existing_config
        else:
            self.modules[key] = config


def parse_modules_json(example_path: Path) -> ModuleExampleConfigs:
    configs = ModuleExampleConfigs(example_path=example_path)
    module_json_path = example_path / MODULES_JSON_RELATIVE_PATH
    if not module_json_path.exists():
        return configs
    module_json = parse_dict(module_json_path)
    for raw in module_json.get("Modules", []):
        with suppress(_RootModuleIgnored):
            config = ModuleExampleConfig(**raw)
            configs.add_module(config)
    return configs
