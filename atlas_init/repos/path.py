from __future__ import annotations
import logging
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

from git import Repo as _GitRepo

from atlas_init.settings.path import current_dir, repo_path_rel_path

logger = logging.getLogger(__name__)
GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS = "mongodb/terraform-provider-mongodbatlas"
GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES = "mongodb/mongodbatlas-cloudformation-resources"
_KNOWN_OWNER_PROJECTS = {
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
}


def package_glob(package_path: str) -> str:
    return f"{package_path}/*.go"


def go_package_prefix(repo_path: Path) -> str:
    owner_project = owner_project_name(repo_path)
    return f"github.com/{owner_project}"


def _owner_project_name(repo_path: Path) -> str:
    owner_project = owner_project_name(repo_path)
    if owner_project not in _KNOWN_OWNER_PROJECTS:
        raise ValueError(f"unknown repo owner @ {repo_path}")
    return owner_project


_resource_roots = {
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: lambda p: p / "internal/service",
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda p: p / "cfn-resources",
}


def _default_is_resource(p: Path) -> bool:
    return "internal/service" in str(p)


_resource_is_resource: dict[str, Callable[[Path], bool]] = {
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda p: (p / "cmd/main.go").exists(),
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: _default_is_resource,
}


def resource_root(repo_path: Path) -> Path:
    owner_project = owner_project_name(repo_path)
    return _resource_roots[owner_project](repo_path)


def is_resource_call(repo_path: Path) -> Callable[[Path], bool]:
    owner_project = owner_project_name(repo_path)
    return _resource_is_resource[owner_project]


def resource_dir(repo_path: Path, full_path: Path) -> Path:
    if dir_name := resource_name(repo_path, full_path):
        return resource_root(repo_path) / dir_name
    else:
        raise ValueError(f"no resource name for {full_path}")


class Repo(StrEnum):
    CFN = "cfn"
    TF = "tf"


def as_repo_alias(path: Path) -> Repo:
    owner = owner_project_name(path)
    return _owner_lookup(owner)


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
    repo_url = next(iter(remote.urls))
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
    return next(
        (parent.name for parent in [full_path, *full_path.parents] if parent.parent == root and is_resource(parent)),
        "",
    )


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
    return _repo_path()


def _repo_path() -> Path:
    repo_path, _ = repo_path_rel_path()
    return repo_path


def find_go_mod_dir(repo_path: Path):
    for go_mod in repo_path.rglob("go.mod"):
        # tf is at root level
        # cfn is at {root}/cfn-resources
        if repo_path in {go_mod.parent, go_mod.parent.parent}:
            return go_mod.parent
    msg = "go.mod not found or more than 1 level deep"
    raise ValueError(msg)


def find_test_names(file: Path, prefix: str = "Test") -> list[str]:
    test_names = []
    with file.open("r") as f:
        for line in f:
            if line.startswith(f"func {prefix}"):
                test_name = line.split("(")[0].strip().removeprefix("func ")
                test_names.append(test_name)
    return sorted(test_names)


class MultipleResourceNames(ValueError):
    def __init__(self, names: list[str]):
        super().__init__(f"multiple resource names found: {names}")
        self.names = names


def find_tf_resource_name_in_test(path: Path, provider_prefix: str = "mongodbatlas_") -> str:
    candidates: set[str] = {
        match.group(1) for match in re.finditer(rf"=\s\"{provider_prefix}([a-zA-Z0-9_]+)\.?", path.read_text())
    }
    if len(candidates) > 1:
        pkg_name = path.parent.name
        for candidate in candidates:
            if candidate.replace("_", "") == pkg_name:
                return candidate
        logger.warning(f"multiple resource names found in {path}: {candidates}")
        raise MultipleResourceNames(sorted(candidates))
    return candidates.pop() if candidates else ""


def find_pkg_test_names(pkg_path: Path, prefix: str = "Test") -> list[str]:
    test_names = []
    for test_file in pkg_path.glob("*_test.go"):
        test_names.extend(find_test_names(test_file, prefix))
    return sorted(test_names)


def terraform_resource_test_names(
    repo_path: Path, prefix: str = "Test", package_path: str = "internal/service"
) -> dict[str, list[str]]:
    """find all test names in the given package path"""
    pkg_path = terraform_package_path(repo_path, package_path)
    resource_dirs, _ = find_resource_dirs(pkg_path)
    test_names = defaultdict(list)
    for name, pkg_dir in resource_dirs.items():
        for test_file in pkg_dir.glob("*_test.go"):
            test_names[name].extend(find_test_names(test_file, prefix))
    return test_names


def terraform_resources(repo_path: Path, package_path: str = "internal/service") -> list[TFResoure]:
    pkg_path = terraform_package_path(repo_path, package_path)
    resource_dirs, _ = find_resource_dirs(pkg_path)
    resources = []
    for name, pkg_dir in resource_dirs.items():
        test_names = find_pkg_test_names(pkg_dir)
        resources.append(TFResoure(name=name, package_rel_path=str(pkg_dir.relative_to(repo_path)), tests=test_names))
    return resources


def terraform_package_path(repo_path: Path, package_path: str = "internal/service"):
    pkg_path = repo_path / package_path
    if not pkg_path.exists():
        raise ValueError(f"package path not found: {pkg_path}")
    return pkg_path


def find_resource_dirs(pkg_path: Path) -> tuple[dict[str, Path], list[Path]]:
    resource_dirs: dict[str, Path] = {}
    non_resource_dirs: list[Path] = []
    for pkg_dir in pkg_path.iterdir():
        if not pkg_dir.is_dir():
            continue
        if pkg_dir.name == "testdata":
            continue
        found = False
        for test_file in pkg_dir.glob("*_test.go"):
            try:
                if name := find_tf_resource_name_in_test(test_file):
                    resource_dirs[name] = pkg_dir
                    found = True
            except MultipleResourceNames as e:
                for name in e.names:
                    resource_dirs[name] = pkg_dir
                found = True
        if not found:
            non_resource_dirs.append(pkg_dir)
    return resource_dirs, non_resource_dirs


@dataclass
class TFResoure:
    name: str
    package_rel_path: str
    tests: list[str]
