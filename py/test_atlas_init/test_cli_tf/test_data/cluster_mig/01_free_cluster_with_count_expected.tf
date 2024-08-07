resource "mongodbatlas_advanced_cluster" "project_cluster_free" {
  count = local.use_free_cluster ? 1 : 0
  project_id = var.project_id
  name = var.cluster_name
  cluster_type = "REPLICASET"
  replication_specs {
    region_configs {
      priority = 7
      region_name = var.region
      provider_name = "TENANT"
      backing_provider_name = "AWS"
      electable_specs {
        instance_size = "M0"
      }
    }
  }
}