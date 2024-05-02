from enum import StrEnum
from pathlib import Path
from typing import NamedTuple

from atlas_init.constants import GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES, GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS, resource_dir, resource_name
from atlas_init.env_vars import current_dir, init_settings
from atlas_init.git_utils import owner_project_name



class Repo(StrEnum):
    CFN = "cfn"
    TF = "tf"

_owner_repos = {
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: Repo.TF,
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: Repo.CFN,
}

def _owner_lookup(owner: str) -> Repo:
    if repo := _owner_repos.get(owner):
        return repo
    raise ValueError(f"unknown repo: {owner}")

def current_repo() -> Repo:
    repo_path = _repo_path()
    owner = owner_project_name(repo_path)
    return _owner_lookup(owner)


class ResourcePaths(NamedTuple):
    repo_path: Path
    resource_path: Path
    resource_name: str


def find_paths(assert_repo: Repo | None = None) -> ResourcePaths:
    repo_path = current_repo_path(assert_repo)
    cwd = current_dir()
    resource_path = resource_dir(repo_path, cwd)
    r_name = resource_name(repo_path, cwd)
    return ResourcePaths(repo_path, resource_path, r_name)

def _assert_repo(expected: Repo | None = None):
    if expected and current_repo() != expected:
        raise ValueError(f"wrong repo, expected {expected} and got {current_repo()}")

def current_repo_path(assert_repo: Repo | None = None) -> Path:
    _assert_repo(assert_repo)
    repo_path = _repo_path()
    return repo_path

def _repo_path() -> Path:
    settings = init_settings()
    repo_path, _ = settings.repo_path_rel_path
    return repo_path
