resource "mongodbatlas_cluster" "test" {
  project_id   = mongodbatlas_project.test.id
  name         = "geoshareded-cluster"
  disk_size_gb = 80
  num_shards   = 1
  cloud_backup = false
  cluster_type = "GEOSHARDED"

  // Provider Settings "block"
  provider_name               = "AWS"
  provider_instance_size_name = "M30"

  replication_specs {
    zone_name  = "Zone 1"
    num_shards = 2
    regions_config {
      region_name     = "US_EAST_1"
      electable_nodes = 3
      priority        = 7
      read_only_nodes = 1
    }
  }

  replication_specs {
    zone_name  = "Zone 2"
    num_shards = 2
    regions_config {
      region_name     = "US_WEST_2"
      electable_nodes = 5
      priority        = 7
      read_only_nodes = 3
      analytics_nodes = 1
    }
  }
}
