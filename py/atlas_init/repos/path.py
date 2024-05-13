from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Callable, NamedTuple

from git import Repo as _GitRepo

from atlas_init.settings.path import current_dir, repo_path_rel_path

GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS = "mongodb/terraform-provider-mongodbatlas"
GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES = (
    "mongodb/mongodbatlas-cloudformation-resources"
)
_KNOWN_OWNER_PROJECTS = {
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
}


def _owner_project_name(repo_path: Path) -> str:
    owner_project = owner_project_name(repo_path)
    if owner_project not in _KNOWN_OWNER_PROJECTS:
        raise ValueError(f"unknown repo owner @ {repo_path}")
    return owner_project


_resource_roots = {
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: lambda p: p / "internal/service",
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda p: p / "cfn-resources",
}


def _default_is_resource(p: Path) -> Callable[[Path], bool]:
    raise NotImplementedError


_resource_is_resource = {
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda p: (
        p / "cmd/main.go"
    ).exists(),
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: _default_is_resource,
}


def resource_root(repo_path: Path) -> Path:
    owner_project = owner_project_name(repo_path)
    return _resource_roots[owner_project](repo_path)


def is_resource_call(repo_path: Path) -> Callable[[Path], bool]:
    owner_project = owner_project_name(repo_path)
    return _resource_is_resource[owner_project]


def resource_dir(repo_path: Path, full_path: Path) -> Path:
    dir_name = resource_name(repo_path, full_path)
    if not dir_name:
        raise ValueError(f"no resource name for {full_path}")
    return resource_root(repo_path) / dir_name


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


@lru_cache
def owner_project_name(repo_path: Path) -> str:
    repo = _GitRepo(repo_path)
    remote = repo.remotes[0]
    repo_url = list(remote.urls)[0]
    repo_url = repo_url.removesuffix(".git")
    *_, owner, project_name = repo_url.split("/")
    if ":" in owner:
        owner = owner.rsplit(":")[1]
    return f"{owner}/{project_name}"


def current_repo() -> Repo:
    repo_path = _repo_path()
    owner = owner_project_name(repo_path)
    return _owner_lookup(owner)


class ResourcePaths(NamedTuple):
    repo_path: Path
    resource_path: Path
    resource_name: str


def resource_name(repo_path: Path, full_path: Path) -> str:
    root = resource_root(repo_path)
    is_resource = is_resource_call(repo_path)
    if not root.exists():
        raise ValueError(f"no resource root found for {repo_path}")
    for parent in [full_path, *full_path.parents]:
        if parent.parent == root:
            if is_resource(parent):
                return parent.name
    return ""


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
    repo_path, _ = repo_path_rel_path()
    return repo_path
