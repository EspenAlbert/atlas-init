from collections import defaultdict
import logging
from pathlib import Path

from atlas_init.cli_tf.hcl.modifier2 import safe_parse, variable_reader, variable_usages

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
