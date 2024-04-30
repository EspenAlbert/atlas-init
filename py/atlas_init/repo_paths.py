from pathlib import Path
from typing import NamedTuple

from atlas_init.constants import resource_dir, resource_name
from atlas_init.env_vars import current_dir, init_settings


class ResourcePaths(NamedTuple):
    repo_path: Path
    resource_path: Path
    resource_name: str


def find_paths() -> ResourcePaths:
    cwd = current_dir()
    settings = init_settings()
    repo_path, _ = settings.repo_path_rel_path
    resource_path = resource_dir(repo_path, cwd)
    r_name = resource_name(repo_path, cwd)
    return ResourcePaths(repo_path, resource_path, r_name)
