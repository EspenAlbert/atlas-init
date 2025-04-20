import pytest

from atlas_init.cli_tf.hcl.modifier import BLOCK_TYPE_OUTPUT, BLOCK_TYPE_VARIABLE, read_block_attribute_object_keys, update_descriptions

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

_existing_descriptions_variables = {
    "cluster_name": [""],
    "provider_name": [""],
    "replication_specs": ["List of replication specifications in legacy "],
}

example_outputs_tf = """provider "mongodbatlas" {
  public_key  = var.public_key
  private_key = var.private_key
}

module "cluster" {
  source = "../../module_maintainer/v3"

  cluster_name           = var.cluster_name
  cluster_type           = var.cluster_type
  mongo_db_major_version = var.mongo_db_major_version
  project_id             = var.project_id
  replication_specs_new  = var.replication_specs_new
  tags                   = var.tags
}

output "mongodb_connection_strings" {
  value = module.cluster.mongodb_connection_strings
}

output "with_desc" {
  value = "with_desc"
  description = "description old"
}
"""
_existing_descriptions_outputs = {
    "mongodb_connection_strings": [""],
    "with_desc": ["description old"],
}


@pytest.mark.parametrize(
    ("block_type", "new_names", "existing_descriptions", "tf_config"),
    [
        (
            BLOCK_TYPE_VARIABLE,
            {
                "cluster_name": 'description of "cluster" name',
                "provider_name": "azure/aws/gcp",
            },
            _existing_descriptions_variables,
            example_variables_tf,
        ),
        (
            BLOCK_TYPE_OUTPUT,
            {
                "with_desc": "description new",
                "mongodb_connection_strings": "new connection strings desc",
            },
            _existing_descriptions_outputs,
            example_outputs_tf,
        ),
    ],
    ids=[BLOCK_TYPE_VARIABLE, BLOCK_TYPE_OUTPUT],
)
def test_process_variables(tmp_path, file_regression, block_type, new_names, existing_descriptions, tf_config):
    example_tf_path = tmp_path / "example.tf"
    example_tf_path.write_text(tf_config)
    new_tf, existing_descriptions = update_descriptions(example_tf_path, new_names, block_type=block_type)
    file_regression.check(new_tf, extension=".tf")
    assert dict(existing_descriptions.items()) == existing_descriptions


out_example_env_vars = """\
output "env_vars" {
  value = {
    MONGODB_ATLAS_PROFILE         = var.cfn_profile
    MONGODB_ATLAS_PUBLIC_API_KEY  = var.atlas_public_key
    MONGODB_ATLAS_PRIVATE_API_KEY = var.atlas_private_key
    # cfn-e2e
    MONGODB_ATLAS_SECRET_PROFILE = var.cfn_profile
    CFN_EXAMPLE_EXECUTION_ROLE   = aws_iam_role.execution_role.arn
  }
  description = "Environment variables for the example"
}
"""

def test_output_env_vars_keys(tmp_path):
    example_tf_path = tmp_path / "example.tf"
    example_tf_path.write_text(out_example_env_vars)
    env_vars = read_block_attribute_object_keys(example_tf_path, block_type=BLOCK_TYPE_OUTPUT, block_name="env_vars", block_key="value")
    assert env_vars == [
        "MONGODB_ATLAS_PROFILE",
        "MONGODB_ATLAS_PUBLIC_API_KEY",
        "MONGODB_ATLAS_PRIVATE_API_KEY",
        "MONGODB_ATLAS_SECRET_PROFILE",
        "CFN_EXAMPLE_EXECUTION_ROLE",
    ]