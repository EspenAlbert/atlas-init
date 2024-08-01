resource "mongodbatlas_advanced_cluster" "multi_region" {
  project_id = mongodbatlas_project.cluster_project.id
  name = "cluster-multi-region"
  disk_size_gb = 100
  backup_enabled = true
  cluster_type = "REPLICASET"
  replication_specs {
    num_shards = 1
    region_configs {
      region_name = "US_WEST_2"
      priority = 6
      provider_name = "AWS"
      electable_specs {
        node_count = 3
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
    }
    region_configs {
      region_name = "US_WEST_1"
      priority = 5
      provider_name = "AWS"
      electable_specs {
        node_count = 1
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
    }
    region_configs {
      region_name = "US_EAST_1"
      priority = 7
      provider_name = "AWS"
      electable_specs {
        node_count = 3
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M10"
        ebs_volume_type = "STANDARD"
      }
    }
  }
}
