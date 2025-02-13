from atlas_init.cli_tf.hcl.modifier import update_descriptions

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


def test_process_variables(tmp_path, file_regression):
    example_variables_tf_path = tmp_path / "example_variables.tf"
    example_variables_tf_path.write_text(example_variables_tf)
    new_names = {
        "cluster_name": "description of cluster name",
        "provider_name": "azure/aws/gcp",
    }
    new_tf, existing_descriptions = update_descriptions(example_variables_tf_path, new_names)
    file_regression.check(new_tf, extension=".tf")
    assert dict(existing_descriptions.items()) == {
        "cluster_name": [""],
        "provider_name": [""],
        "replication_specs": ["List of replication specifications in legacy " "mongodbatlas_cluster format"],
    }
