# Cluster Module PoC - Option 2 Flat Variables Python
- This module maps all the attributes of [`mongodbatlas_advanced_cluster (preview provider 2.0.0)`](https://registry.terraform.io/providers/mongodb/mongodbatlas/latest/docs/resources/advanced_cluster%2520%2528preview%2520provider%25202.0.0%2529) to [variables.tf](variables.tf).
- Remember to set the `export MONGODB_ATLAS_ADVANCED_CLUSTER_V2_SCHEMA=true` in your terminal before running `terraform` commands.
- It also supports `auto_scaling`
- All deprecated fields are removed
- Caveat:
  - This module requires a `python3.7` or later runtime

## Known Limitations (not prioritized due to limited time)
- Only supports `disk_size_gb` at root level
- No support for `disk_iops` or `ebs_volume_type`

<!-- BEGIN_DISCLAIMER -->
REPLACE_DISCLAIMER
<!-- END_DISCLAIMER -->

<!-- BEGIN_TF_EXAMPLES -->
REPLACE_TF_EXAMPLES
<!-- END_TF_EXAMPLES -->

<!-- BEGIN_TF_DOCS -->

<!-- END_TF_DOCS -->
