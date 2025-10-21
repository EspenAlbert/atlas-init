from os import getenv
import os
from typing import Any
from unittest.mock import MagicMock
from pathlib import Path

import pytest
from atlas_init.cli_tf.hcl.modifier2 import TFVar
from atlas_init.tf_ext.paths import ResourceVarUsage, find_resource_types_with_usages, find_variables_typed
from atlas_init.tf_ext.tf_vars import parse_all_variables


def test_parse_all_variables(tf_variables_path):
    vars_usage = parse_all_variables([tf_variables_path.parent, tf_variables_path.parent], MagicMock())
    shortened_vars = {key: str(value) for key, value in vars_usage.root.items()}
    assert (
        shortened_vars["org_id"]
        == "TfVarUsage(name='org_id',descriptions={'Unique 24-hexadecimal digit string that identifies your Atlas Organization'},paths_str='/mongodbatlas_stream_instance')"
    )


def test_parse_resource_types(tf_push_based_log_example):
    usages = find_resource_types_with_usages(tf_push_based_log_example.parent)
    assert "mongodbatlas_push_based_log_export" in usages.root
    assert usages.root["mongodbatlas_push_based_log_export"].example_files[0].name == "main.tf"
    assert not usages.root["mongodbatlas_push_based_log_export"].variable_usage
    assert "mongodbatlas_project" in usages.root
    assert usages.root["mongodbatlas_project"].variable_usage == [
        ResourceVarUsage(var_name="atlas_project_name", attribute_path="name"),
        ResourceVarUsage(var_name="atlas_org_id", attribute_path="org_id"),
    ]
    assert "aws_s3_bucket" in usages.root
    assert usages.root["aws_s3_bucket"].variable_usage == [
        ResourceVarUsage(var_name="s3_bucket_name", attribute_path="bucket"),
    ]


_input_variables = """\
variable "name" {
  description = "Human-readable label that identifies this cluster."
  type        = string
}

variable "regions" {
  description = <<-EOT
The simplest way to define your cluster topology:
- For REPLICASET: omit both `shard_number` and `zone_name`.
- For SHARDED: set `shard_number` on each region; do not set `zone_name`. Regions with the same `shard_number` belong to the same shard.
- GEOSHARDED: set `zone_name` on each region; optionally set `shard_number`. Regions with the same `zone_name` form one zone.

Note: The order in which region blocks are defined in this list determines their priority within each shard or zone. The first region gets priority 7 (maximum), the next 6, and so on (minimum 0).
EOT
  type = list(object({
    name                    = optional(string)
    node_count              = optional(number)
    shard_number            = optional(number)
    provider_name           = optional(string)
    node_count_read_only    = optional(number)
    node_count_analytics    = optional(number)
    instance_size           = optional(string)
    instance_size_analytics = optional(string)
    zone_name               = optional(string)
  }))

  validation {
    error_message = "Only provider_name AWS/AZURE/GCP are allowed."
    condition     = length([for region in var.regions : region if region.provider_name != null && !contains(["AWS", "AZURE", "GCP"], region.provider_name)]) == 0
  }

  validation {
    error_message = "M0, M2, and M5 are not allowed for this module. Use M10 or higher instead."
    condition     = length([for region in var.regions : region if region.instance_size != null && (region.instance_size == "M0" || region.instance_size == "M2" || region.instance_size == "M5")]) == 0
  }

  validation {
    error_message = "no node count specified at indexes ${join(",", [for idx, region in var.regions : idx if alltrue([region.node_count == null, region.node_count_read_only == null, region.node_count_analytics == null])])}"
    condition     = length([for idx, region in var.regions : idx if alltrue([region.node_count == null, region.node_count_read_only == null, region.node_count_analytics == null])]) == 0
  }
}
variable "advanced_configuration" {
  description = "Additional settings for an Atlas cluster."
  type = object({
    change_stream_options_pre_and_post_images_expire_after_seconds = optional(number)
    custom_openssl_cipher_config_tls12                             = optional(list(string))
    default_max_time_ms                                            = optional(number)
    default_write_concern                                          = optional(string, "majority")
    javascript_enabled                                             = optional(bool, false)
    minimum_enabled_tls_protocol                                   = optional(string, "TLS1_2")
    no_table_scan                                                  = optional(bool)
    oplog_min_retention_hours                                      = optional(number)
    oplog_size_mb                                                  = optional(number)
    sample_refresh_interval_bi_connector                           = optional(number)
    sample_size_bi_connector                                       = optional(number)
    tls_cipher_config_mode                                         = optional(string)
    transaction_lifetime_limit_seconds                             = optional(number)
  })
  nullable = true
  default = {
    default_write_concern        = "majority"
    javascript_enabled           = false
    minimum_enabled_tls_protocol = "TLS1_2"
  }
}
"""


def format_type(type: str) -> list[str]:
    if "\n" in type:
        return ["Type:", "", "```hcl", type, "```", ""]
    return [f"Type: `{type}`"]


def format_default(name, default: Any) -> list[str]:
    if default is None:
        return ["Default: `null`"]
    if isinstance(default, str) and "\n" in default:
        return ["Default:", "", "```hcl", f"{name} = {default}", "```", ""]
    return ["Default:", "", "```hcl", f"{name} = {default}", "```", ""]


def as_md(name: str, tf_var: TFVar) -> list[str]:
    return [
        f"### {name}",
        *([f"Description: {tf_var.description.strip('"')}", ""] if tf_var.description else []),
        *([f"Sensitive: {tf_var.sensitive}", ""] if tf_var.sensitive else []),
        *(format_type(tf_var.type) if tf_var.type else []),
        *(format_default(name, tf_var.default) if tf_var.is_default_set else []),
        "",
    ]


def as_inputs(groups: dict[str, list[str]], default_group: str, variables: dict[str, TFVar]) -> list[str]:
    md_lines: list[str] = []
    used_vars: set[str] = set()

    def group_title(name: str) -> str:
        return f"## {name.title()}\n"

    def add_var(name: str) -> list[str]:
        if name in used_vars:
            return []
        used_vars.add(name)
        return as_md(name, variables[name])

    for group, group_variables in groups.items():
        md_lines.append(group_title(group))
        for var in group_variables:
            md_lines.extend(add_var(var))
    md_lines.append(group_title(default_group))
    for var in sorted(variables):
        md_lines.extend(add_var(var))
    return md_lines


def test_generate_inputs_md(tmp_path, file_regression):
    full = tmp_path / "variables.tf"
    full.write_text(_input_variables)
    parsed = find_variables_typed(full)
    assert sorted(parsed) == ["advanced_configuration", "name", "regions"]
    print(as_md("advanced_configuration", parsed["advanced_configuration"]))


@pytest.mark.skipif(os.environ.get("CLUSTER_MODULE_PATH", "") == "", reason="needs os.environ['CLUSTER_MODULE_PATH']")
def test_generate_inputs_md_cluster(tmp_path, file_regression):
    path = getenv("CLUSTER_MODULE_PATH")
    assert path
    tf_files = list(Path(path).glob("*.tf"))
    variables: dict[str, TFVar] = {}
    for tf_file in tf_files:
        variables |= find_variables_typed(tf_file)
    groups = {
        "Required Variables": ["project_id", "name", "cluster_type"],
        "Cluster Topology `regions` (Option 1)": ["regions", "provider_name"],
        "Cluster Topology `regions` Auto Scaling": [
            "auto_scaling",
            "auto_scaling_analytics",
        ],
        "Cluster Topology `regions` Manual Scaling": [
            "instance_size",
            "instance_size_analytics",
            "disk_size_gb",
            "disk_iops",
            "ebs_volume_type",
        ],
        "Cluster Topology `replication_specs` (Option 2)": ["replication_specs"],
        "Production Recommendations (Enabled by default)": [
            "advanced_configuration",
            "backup_enabled",
            "pit_enabled",
            "retain_backups_enabled",
        ],
        "Production Recommendations (Manually configured)": [
            "encryption_at_rest_provider",
            "redact_client_log_data",
            "tags",
            "termination_protection_enabled",
        ],
    }
    inputs_lines = as_inputs(groups, "Optional Variables", variables)
    md = "\n".join(inputs_lines)
    file_regression.check(md, extension=".md")
