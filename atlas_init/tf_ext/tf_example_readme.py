from collections import defaultdict
from contextlib import suppress
from functools import total_ordering
import logging
from pathlib import Path
from typing import ClassVar
from ask_shell import new_task
from ask_shell.rich_live import get_live_console
from model_lib import Entity, parse_dict
from pydantic import Field, model_validator
import pydot
from rich.tree import Tree
import typer

from atlas_init.tf_ext.tf_dep import EdgeParsed, ResourceRef, node_plain, parse_graphs

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
    # settings = init_tf_ext_settings()
    # out_dir = settings.cache_root / example_path.name
    # with new_task("parse example graph"):
    #     _, graph_output = parse_graph(example_path)
    modules_configs = parse_modules_json(example_path)
    modules = modules_configs.modules_included(skip_keys=skip_module_keys)
    assert modules, f"no modules found in {example_path} that are not in {skip_module_keys} (skip_module_keys)"
    module_paths = [example_path / module.rel_path for module in modules]
    if not_found_paths := [path for path in module_paths if not path.exists()]:
        raise ValueError(f"module paths not found: {not_found_paths}")
    with new_task("parse module graphs") as task:
        example_graphs: dict[Path, ResourceGraph] = {}

        def on_graph(example_dir: Path, graph: pydot.Dot):
            example_graphs[example_dir] = ResourceGraph.from_graph(graph)
            # TODO: Test this with the 03_alert_configuration

        parse_graphs(on_graph, module_paths, task)
    for example_dir, example_graph in example_graphs.items():
        tree = example_graph.to_tree(example_dir.name, include_orphans=True)
        get_live_console().print(tree)

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


class _RootModuleIgnored(Exception):
    pass


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

    def all_edges(self) -> list[tuple[ResourceRef, ResourceRef]]:
        return [(parent, child) for parent in self.parent_children for child in self.parent_children[parent]]

    @property
    def all_parents(self) -> set[ResourceRef]:
        return set(self.parent_children.keys())

    def to_tree(self, example_dir_name: str, include_orphans: bool = False) -> Tree:
        root = Tree(example_dir_name)
        remaining_parents = self.all_parents
        used_parents = set()
        trees: dict[ResourceRef, Tree] = {}

        def next_parent() -> ResourceRef | None:
            candidates = [parent for parent in remaining_parents if not self.children_parents[parent] - used_parents]
            return min(candidates) if candidates else None

        while remaining_parents:
            parent = next_parent()
            if parent is None:
                break
            used_parents.add(parent)
            parent_tree = trees.setdefault(parent, Tree(parent.full_ref))
            for child_ref in sorted(self.parent_children[parent]):
                child_tree = trees.setdefault(child_ref, Tree(child_ref.full_ref))
                parent_tree.add(child_tree)
            remaining_parents.remove(parent)
            if not self.children_parents[parent]:
                root.add(parent_tree)

        if include_orphans:
            for orphan in self.orphans:
                if orphan not in trees:
                    root.add(Tree(orphan.full_ref))
        return root


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
    modules: dict[str, ModuleExampleConfig] = Field(default_factory=dict)

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
    configs = ModuleExampleConfigs()
    module_json_path = example_path / MODULES_JSON_RELATIVE_PATH
    if not module_json_path.exists():
        return configs
    module_json = parse_dict(module_json_path)
    for raw in module_json.get("Modules", []):
        with suppress(_RootModuleIgnored):
            config = ModuleExampleConfig(**raw)
            configs.add_module(config)
    return configs
