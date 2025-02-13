from atlas_init.cli_tf.example_vars import UpdateExampleVars, VarDescriptionChange, update_example_vars


def test_description_change(tmp_path):
    assert VarDescriptionChange(
        path=tmp_path,
        name="cluster_name",
        before="",
        after="description of cluster name",
    ).changed
    assert not VarDescriptionChange(
        path=tmp_path,
        name="cluster_name",
        before="description of cluster name",
        after="description of cluster name",
    ).changed
    assert not VarDescriptionChange(
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


def test_update_example_vars(tmp_path, file_regression):
    base_dir = tmp_path / "example_base"
    base_dir.mkdir()
    example_variables_tf_path = base_dir / "example_variables.tf"
    example_variables_tf_path.write_text(example_variables_tf)
    output = update_example_vars(
        UpdateExampleVars(
            examples_base_dir=base_dir,
            var_descriptions={
                "cluster_name": "description of cluster name",
                "replication_specs": "Updated description",
            },
        )
    )
    assert output.before_descriptions == {
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
