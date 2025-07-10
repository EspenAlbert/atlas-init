from __future__ import annotations
from typing import Self

from model_lib import Entity
from pydantic import Field, RootModel, model_validator

from atlas_init.tf_ext.tf_dep import AtlasGraph

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
    "1️⃣1️⃣",
    "1️⃣2️⃣",
]
_emoji_counter = 0


def choose_next_emoji() -> str:
    global _emoji_counter
    emoji = _emojii_list[_emoji_counter]
    _emoji_counter += 1
    return emoji


class ModuleState(Entity):
    resource_types: set[str] = Field(default_factory=set, description="Set of resource types in the module.")


def default_allowed_multi_parents() -> set[str]:
    return {
        "mongodbatlas_project",
    }


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
        if child in atlas_graph.deprecated_resource_types:
            return False
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
    def module_emoji_prefix(self, resource_type: str) -> str:
        """Get the emoji prefix for a resource type based on its module."""
        return next(
            (
                module_config.emojii
                for module_config in self.root.values()
                if resource_type in module_config.state.resource_types
            ),
            "",
        )
