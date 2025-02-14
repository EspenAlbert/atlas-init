import os
from pathlib import Path

import pytest

from atlas_init.cli_tf.example_update import (
    TFConfigDescriptionChange,
    UpdateExamples,
    update_examples,
)
from atlas_init.cli_tf.hcl.modifier import BLOCK_TYPE_VARIABLE, update_descriptions


def test_description_change(tmp_path):
    assert TFConfigDescriptionChange(
        block_type=BLOCK_TYPE_VARIABLE,
        path=tmp_path,
        name="cluster_name",
        before="",
        after="description of cluster name",
    ).changed
    assert not TFConfigDescriptionChange(
        block_type=BLOCK_TYPE_VARIABLE,
        path=tmp_path,
        name="cluster_name",
        before="description of cluster name",
        after="description of cluster name",
    ).changed
    assert not TFConfigDescriptionChange(
        block_type=BLOCK_TYPE_VARIABLE,
        path=tmp_path,
        name="cluster_name",
        before="description of cluster name",
        after="",
    ).changed


example_variables_tf = """variable "cluster_name" {
  type = string
}
variable "replication_specs" {
  description = "List of replication specifications in legacy mongodbatlas_cluster format"
  default     = []
  type = list(object({
    num_shards = number
    zone_name  = string
    regions_config = set(object({
      region_name     = string
      electable_nodes = number
      priority        = number
      read_only_nodes = optional(number, 0)
    }))
  }))
}

variable "provider_name" {
  type    = string
  default = "" # optional in v3
}
"""


def test_update_example(tmp_path, file_regression):
    base_dir = tmp_path / "example_base"
    base_dir.mkdir()
    example_variables_tf_path = base_dir / "example_variables.tf"
    example_variables_tf_path.write_text(example_variables_tf)
    output = update_examples(
        UpdateExamples(
            examples_base_dir=base_dir,
            var_descriptions={
                "cluster_name": "description of cluster name",
                "replication_specs": "Updated description",
            },
        )
    )
    assert output.before_var_descriptions == {
        "cluster_name": "",
        "provider_name": "",
        "replication_specs": "List of replication specifications in legacy mongodbatlas_cluster format",
    }
    assert len(output.changes) == 3  # noqa: PLR2004
    assert [
        ("cluster_name", True),
        ("provider_name", False),
        ("replication_specs", True),
    ] == [(change.name, change.changed) for change in output.changes]
    file_regression.check(example_variables_tf_path.read_text(), extension=".tf")


@pytest.mark.skipif(os.environ.get("TF_FILE", "") == "", reason="needs os.environ[TF_FILE]")
def test_parsing_tf_file():
    file = Path(os.environ["TF_FILE"])
    assert file.exists()
    response, _ = update_descriptions(file, {}, block_type=BLOCK_TYPE_VARIABLE)
    assert response
