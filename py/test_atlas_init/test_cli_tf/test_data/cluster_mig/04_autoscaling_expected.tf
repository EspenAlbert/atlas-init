resource "mongodbatlas_advanced_cluster" "autoscaling" {
  project_id = var.project_id
  name = "with-auto-scaling"
  disk_size_gb = 100
  cluster_type = "REPLICASET"
  backup_enabled = true
  replication_specs {
    num_shards = 1
    region_configs {
      region_name = "US_WEST_2"
      priority = 7
      provider_name = "AWS"
      auto_scaling {
        disk_gb_enabled = true
        compute_enabled = true
        compute_min_instance_size = "M10"
        compute_max_instance_size = "M40"
        compute_scale_down_enabled = true
      }
      electable_specs {
        node_count = 3
        instance_size = "M20"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M20"
      }
    }
  }
  lifecycle { // To simulate if there a new instance size name to avoid scale cluster down to original value
    ignore_changes = [provider_instance_size_name]
  }
}
