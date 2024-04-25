from pathlib import Path

import stringcase
from pydantic import ConfigDict

GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS = "mongodb/terraform-provider-mongodbatlas"
GH_OWNER_MONGODBATLAS_CLOUDFORMATION_RESOURCES = (
    "mongodb/mongodbatlas-cloudformation-resources"
)


def cfn_examples_dir(repo_path: Path) -> Path:
    return repo_path / "examples"


PascalAlias = ConfigDict(alias_generator=stringcase.pascalcase, populate_by_name=True)
