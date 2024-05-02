from pathlib import Path
from typing import Callable

import stringcase
from pydantic import ConfigDict

from atlas_init.git_utils import owner_project_name as git_owner_project_name

GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS = "mongodb/terraform-provider-mongodbatlas"
GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES = (
    "mongodb/mongodbatlas-cloudformation-resources"
)
_KNOWN_OWNER_PROJECTS = {
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES,
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
}


def owner_project_name(repo_path: Path) -> str:
    owner_project = git_owner_project_name(repo_path)
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
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: _default_is_resource
}

_format_cmd = {
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS: lambda p: "golangci-lint run",
    # todo: understand why piping to grep doesn't work
    # GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda r_name: f"golangci-lint run --path-prefix=./cfn-resources | grep {r_name}",
    GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES: lambda _: "golangci-lint run --path-prefix=./cfn-resources",
}


def cfn_examples_dir(repo_path: Path) -> Path:
    return repo_path / "examples"


def resource_root(repo_path: Path) -> Path:
    owner_project = owner_project_name(repo_path)
    return _resource_roots[owner_project](repo_path)


def is_resource_call(repo_path: Path) -> Callable[[Path], bool]:
    owner_project = owner_project_name(repo_path)
    return _resource_is_resource[owner_project]


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


def resource_dir(repo_path: Path, full_path: Path) -> Path:
    dir_name = resource_name(repo_path, full_path)
    if not dir_name:
        raise ValueError(f"no resource name for {full_path}")
    return resource_root(repo_path) / dir_name


def format_cmd(repo_path: Path, resource_name: str) -> str:
    owner_project = owner_project_name(repo_path)
    return _format_cmd[owner_project](resource_name)


def go_sdk_breaking_changes(
    repo_path: Path, go_sdk_rel_path: str = "../atlas-sdk-go"
) -> Path:
    rel_path = "tools/releaser/breaking_changes"
    breaking_changes_dir = repo_path / go_sdk_rel_path / rel_path
    breaking_changes_dir = breaking_changes_dir.absolute()
    assert (
        breaking_changes_dir.exists()
    ), f"not found breaking_changes={breaking_changes_dir}"
    return breaking_changes_dir


PascalAlias = ConfigDict(alias_generator=stringcase.pascalcase, populate_by_name=True)
