from pathlib import Path

import stringcase
from pydantic import ConfigDict

GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS = "mongodb/terraform-provider-mongodbatlas"
GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES = (
    "mongodb/mongodbatlas-cloudformation-resources"
)


def cfn_examples_dir(repo_path: Path) -> Path:
    return repo_path / "examples"


def resource_name(repo_path: Path, full_path: Path) -> str:
    resource_dir_cfn = repo_path / "cfn-resources"
    resource_dir_tf = repo_path / "internal/service"

    def is_resource_cfn(p: Path) -> bool:
        return (p / "cmd/main.go").exists()

    for resource_dir, is_resource in {resource_dir_tf: lambda p: True, resource_dir_cfn: is_resource_cfn}.items():
        if not resource_dir.exists():
            continue
        for parent in full_path.parents:
            if parent.parent == resource_dir:
                if is_resource(parent):
                    return parent.name
    return ""


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
