resource "mongodbatlas_cluster" "multi_region" {
  project_id   = mongodbatlas_project.cluster_project.id
  name         = "cluster-multi-region"
  disk_size_gb = 100
  num_shards   = 1
  cloud_backup = true
  cluster_type = "REPLICASET"

  // Provider Settings "block"
  provider_name               = "AWS"
  provider_instance_size_name = "M10"

  replication_specs {
    num_shards = 1
    dynamic "regions_config" {
      for_each = {
        US_WEST_2 = {
          electable_nodes = 3
          priority        = 6
          read_only_nodes = 0
        }
        US_WEST_1 = {
          electable_nodes = 1
          priority        = 5
          read_only_nodes = 0
        }
        US_EAST_1 = {
          electable_nodes = 3
          priority        = 7
          read_only_nodes = 0
        }
      }
      content {
        region_name = "value"
        electable_nodes = regions_config.value.electable_nodes
        priority        = regions_config.value.priority
        read_only_nodes = regions_config.value.read_only_nodes
      }
      
    }
  }
}
