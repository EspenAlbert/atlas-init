import logging
import os
from pathlib import Path
import re
import pytest

from atlas_init.cli_tf.hcl.cli import convert_and_validate, ensure_no_plan_changes
from atlas_init.cli_tf.hcl.cluster_mig import (
    convert_cluster_config,
    convert_clusters,
    parse_and_convert_cluster_blocks,
)

logger = logging.getLogger(__name__)


def read_examples() -> list[tuple[str, str, str]]:
    TEST_DATA = Path(__file__).parent / "test_data/cluster_mig"

    def as_test_case(path: Path) -> tuple[str, str, str]:
        filename = path.name.replace("_expected", "")
        return filename, (path.parent / filename).read_text(), path.read_text()

    return sorted([as_test_case(path) for path in TEST_DATA.glob("*_expected.tf")])


examples = read_examples()
ERROR_PREFIX = "# error: "


@pytest.mark.parametrize(
    "name,legacy,expected", examples, ids=[name for name, *_ in examples]
)
def test_convert_cluster(name, legacy, expected):
    if expected.startswith(ERROR_PREFIX):
        with pytest.raises(ValueError) as exc:
            convert_cluster_config(legacy)
        assert str(exc.value) == expected.removeprefix(ERROR_PREFIX)
        return
    new_config = convert_cluster_config(legacy)
    print(f"new config for name: {name}f")
    print(new_config)
    assert new_config == expected


@pytest.mark.skipif(
    os.environ.get("TF_DIR", "") == "", reason="needs os.environ[TF_DIR]"
)
def test_live_no_plan_changes():
    tf_dir = Path(os.environ["TF_DIR"])
    assert convert_clusters(tf_dir)

_main_tf = """\
terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.16.0"
    }
  }
}
provider "mongodbatlas" {
}

variable "instance_size" {
  type = string
  default = "M10"
}
variable "region" {
  type = string
  default = "US_EAST_1"
}

locals {
    use_free_cluster = true
}

resource "mongodbatlas_project" "this" {
  name = "pytest"
  org_id = "ORG_ID"
}
"""

def _replace_project_id_and_cluster_name(hcl: str, name: str) -> str:
    project_id_pattern = re.compile(r'^\s+project_id\s*=(.*)$', re.M)
    hcl = project_id_pattern.sub(r'  project_id = mongodbatlas_project.this.id', hcl)
    name_pattern = re.compile(r'^\s+name\s*=(.*)$', re.M)
    return name_pattern.sub(rf'  name = "{name}"', hcl)

_example = """\
resource "mongodbatlas_cluster" "this" {
  project_id = "ORG_ID"
  name = "pytest-cluster"
  cluster_type = "REPLICASET"
}"""

def test_replace_project_id_and_cluster_name():
    assert _replace_project_id_and_cluster_name(_example, "pytest") == """\
resource "mongodbatlas_cluster" "this" {
  project_id = mongodbatlas_project.this.id
  name = "pytest"
  cluster_type = "REPLICASET"
}"""



def _project_main_tf(org_id: str) -> str:
    return _main_tf.replace("ORG_ID", org_id)

def _shorten_name(name: str) -> str:
    return Path(name).stem.split("_", maxsplit=1)[1].replace("_", "-")

@pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in ["MONGODB_ATLAS_BASE_URL", "TF_DIR", "MONGODB_ATLAS_PUBLIC_KEY", "MONGODB_ATLAS_PRIVATE_KEY", "MONGODB_ATLAS_ORG_ID"]),
    reason='needs env vars: ["MONGODB_ATLAS_BASE_URL", "TF_DIR", "MONGODB_ATLAS_PUBLIC_KEY", "MONGODB_ATLAS_PRIVATE_KEY", "MONGODB_ATLAS_ORG_ID"]),',
)
def test_generated_examples_actually_has_no_plan_changes():
    tf_dir = Path(os.environ["TF_DIR"])
    org_id = os.environ["MONGODB_ATLAS_ORG_ID"]
    main_tf_content = _project_main_tf(org_id)
    main_tf_path = tf_dir / "main.tf"
    main_tf_path.write_text(main_tf_content)
    for name, legacy, expected in examples:
        if expected.startswith(ERROR_PREFIX):
            continue
        if name in {"03_geosharded_with_nodes.tf"}:
            continue
        cluster_path = tf_dir / name
        cluster_path.write_text(_replace_project_id_and_cluster_name(legacy, _shorten_name(name)))
    ensure_no_plan_changes(tf_dir)
    convert_and_validate(tf_dir, is_interactive=False)

@pytest.mark.skipif(os.environ.get("CLI_TF_HCL_PATH", "") == "", reason="needs os.environ[CLI_TF_HCL_PATH]")
def test_generate_standalone_script():
    CLI_TF_HCL_PATH = Path(os.environ["CLI_TF_HCL_PATH"])
    assert CLI_TF_HCL_PATH.is_dir()
    full_content = []
    for path in sorted(CLI_TF_HCL_PATH.glob("*.py")):
        content = path.read_text()
        full_content.append("# " + str(path.stem))
        full_content.append(content)
    print("full script:")
    print("\n\n".join(full_content))
