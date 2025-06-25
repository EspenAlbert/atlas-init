from collections import defaultdict
import logging
from pathlib import Path

from model_lib import Entity
from pydantic import Field, RootModel
from zero_3rdparty.file_utils import iter_paths

from atlas_init.cli_tf.hcl.modifier2 import resource_types_vars_usage, safe_parse, variable_reader, variable_usages

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


class ResourceTypeUsage(Entity):
    name: str
    example_files: list[Path] = Field(default_factory=list)
    variable_usage: list[ResourceVarUsage] = Field(default_factory=list)

    def add_usage(self, example_files: list[Path], variable_usages: list[ResourceVarUsage]):
        for example_file in example_files:
            if example_file not in self.example_files:
                self.example_files.append(example_file)
        self.variable_usage.extend(variable_usages)


class ResourceTypes(RootModel[dict[str, ResourceTypeUsage]]):
    def add_resource_type(self, resource_type: str, example_files: list[Path], variable_usages: list[ResourceVarUsage]):
        if resource_type not in self.root:
            self.root[resource_type] = ResourceTypeUsage(name=resource_type)
        resource_type_usage = self.root[resource_type]
        resource_type_usage.add_usage(example_files, variable_usages)


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
