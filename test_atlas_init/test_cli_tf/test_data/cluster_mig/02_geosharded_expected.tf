resource "mongodbatlas_advanced_cluster" "geosharded" {
  project_id = mongodbatlas_project.test.id
  name = "geoshareded-cluster"
  disk_size_gb = 80
  backup_enabled = false
  cluster_type = "GEOSHARDED"
  replication_specs {
    zone_name = "Zone 1"
    num_shards = 2
    region_configs {
      region_name = "US_EAST_1"
      priority = 7
      provider_name = "AWS"
      electable_specs {
        node_count = 3
        instance_size = "M30"
        ebs_volume_type = "STANDARD"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M30"
        ebs_volume_type = "STANDARD"
      }
    }
  }
  replication_specs {
    zone_name = "Zone 2"
    num_shards = 2
    region_configs {
      region_name = "US_WEST_2"
      priority = 7
      provider_name = "AWS"
      electable_specs {
        node_count = 3
        instance_size = "M30"
        ebs_volume_type = "STANDARD"
      }
      read_only_specs {
        node_count = 0
        instance_size = "M30"
        ebs_volume_type = "STANDARD"
      }
    }
  }
}
