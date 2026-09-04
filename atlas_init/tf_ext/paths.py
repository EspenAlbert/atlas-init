from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
import re
from typing import Self

from model_lib import Entity
from pydantic import Field, RootModel
from zero_3rdparty.file_utils import iter_paths

from atlas_init.cli_tf.hcl.modifier2 import (
    TFVar,
    resource_types_vars_usage,
    safe_parse,
    variable_reader,
    variable_reader_typed,
    variable_usages,
)
from atlas_init.tf_ext.constants import ATLAS_PROVIDER_NAME, DEFAULT_EXTERNAL_SUBSTRINGS, DEFAULT_INTERNAL_SUBSTRINGS

logger = logging.getLogger(__name__)


def find_example_dirs(repo_path: Path) -> list[Path]:
    example_dirs: set[Path] = {
        tf_file.parent for tf_file in (repo_path / "examples").rglob("*.tf") if ".terraform" not in tf_file.parts
    }
    return sorted(example_dirs)


def get_example_directories(repo_path: Path, skip_names: list[str]):
    example_dirs = find_example_dirs(repo_path)
    logger.info(f"Found {len(example_dirs)} exaple directories in {repo_path}")
    if skip_names:
        len_before = len(example_dirs)
        example_dirs = [d for d in example_dirs if d.name not in skip_names]
        logger.info(f"Skipped {len_before - len(example_dirs)} example directories with names: {skip_names}")
    return example_dirs


def _extract_variable_part(text_raw: str, var_name: str, attribute_name: str) -> str:
    variable_start = text_raw.find(f'variable "{var_name}" {{')
    assert variable_start > -1, f"variable not found: {var_name}"
    variable_end = text_raw.find("\n}", variable_start)
    assert variable_end > -1, f"variable end not found: {var_name}"
    attribute_start_str = f"  {attribute_name} = "
    type_start = text_raw.find(attribute_start_str, variable_start, variable_end)
    if type_start == -1:
        return ""
    attribute_value_start = type_start + len(attribute_start_str)
    if ending_brackets := re.search(r"^\s{2}[\)\}]+$", text_raw[attribute_value_start:variable_end], re.M):
        attribute_end_relative = ending_brackets.end()
        end = attribute_value_start + attribute_end_relative
        return text_raw[attribute_value_start:end]
    return ""


def find_variables_typed(variables_tf: Path) -> dict[str, TFVar]:
    if not variables_tf.exists():
        return {}
    tree = safe_parse(variables_tf)
    if not tree:
        logger.warning(f"Failed to parse {variables_tf}")
        return {}
    vars_typed = variable_reader_typed(tree)
    text_raw = variables_tf.read_text()
    for name, tf_var in vars_typed.items():
        if tf_var.type and '"' in tf_var.type:
            if new_type := _extract_variable_part(text_raw, name, "type"):
                tf_var.type = new_type
        if tf_var.default is not None:
            if new_default := _extract_variable_part(text_raw, name, "default"):
                tf_var.default = new_default
    return vars_typed


def find_variables(variables_tf: Path) -> dict[str, str | None]:
    if not variables_tf.exists():
        return {}
    tree = safe_parse(variables_tf)
    if not tree:
        logger.warning(f"Failed to parse {variables_tf}")
        return {}
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


class ResourceVarUsage(Entity):
    var_name: str
    attribute_path: str


def is_variable_name_external(
    name: str, external_substrings: list[str] | None = None, internal_substrings: list[str] | None = None
) -> bool:
    external_substrings = external_substrings or DEFAULT_EXTERNAL_SUBSTRINGS
    internal_substrings = internal_substrings or DEFAULT_INTERNAL_SUBSTRINGS
    if any(substring in name for substring in internal_substrings):
        return False
    return any(substring in name for substring in external_substrings)


class ResourceTypeUsage(Entity):
    name: str
    example_files: list[Path] = Field(default_factory=list)
    variable_usage: list[ResourceVarUsage] = Field(default_factory=list)

    def add_usage(self, example_files: list[Path], variable_usages: list[ResourceVarUsage]):
        for example_file in example_files:
            if example_file not in self.example_files:
                self.example_files.append(example_file)
        self.variable_usage.extend(variable_usages)

    @property
    def external_var_usages(self) -> list[str]:
        return [usage.var_name for usage in self.variable_usage if is_variable_name_external(usage.var_name)]


class ResourceTypes(RootModel[dict[str, ResourceTypeUsage]]):
    def add_resource_type(self, resource_type: str, example_files: list[Path], variable_usages: list[ResourceVarUsage]):
        if resource_type not in self.root:
            self.root[resource_type] = ResourceTypeUsage(name=resource_type)
        resource_type_usage = self.root[resource_type]
        resource_type_usage.add_usage(example_files, variable_usages)

    def atlas_resource_type_with_external_var_usages(self) -> Self:
        return type(self)(
            root={
                name: usage
                for name, usage in self.root.items()
                if name.startswith(ATLAS_PROVIDER_NAME) and usage.external_var_usages
            }
        )

    def dump_with_external_vars(self) -> dict[str, dict]:
        return {
            name: usages.model_dump() | {"external_var_usages": usages.external_var_usages}
            for name, usages in self.root.items()
        }


def find_resource_types_with_usages(example_dir: Path):
    output = ResourceTypes(root={})
    for path in iter_paths(example_dir, "*.tf", exclude_folder_names=[".terraform"]):
        tree = safe_parse(path)
        if not tree:
            logger.warning(f"Failed to parse {path}")
            continue
        type_var_usages = resource_types_vars_usage(tree)
        for resource_type, var_usages in type_var_usages.items():
            variable_usages = [
                ResourceVarUsage(var_name=variable_name, attribute_path=attribute_path)
                for variable_name, attribute_path in var_usages.items()
            ]
            output.add_resource_type(resource_type, example_files=[path], variable_usages=variable_usages)
    return output
