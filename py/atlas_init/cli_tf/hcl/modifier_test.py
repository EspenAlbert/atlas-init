import hcl2

from atlas_init.cli_tf.hcl.modifier import process_variables

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
    tree = hcl2.parses(example_variables_tf_path.read_text())
    new_tree = process_variables(tree, {"cluster_name": "description of cluster name", "provider_name": "azure/aws/gcp"})
    reconstructed = hcl2.writes(new_tree)
    file_regression.check(reconstructed, extension=".tf")

