variable "cluster_name" {
  type = string
}
variable "project_id" {
  type = string
}
variable "instance_size" {
  type = string
}

variable "region" {
  type = string
}

variable "mongo_user" {
  type = string
}
variable "mongo_password" {
  type = string
}
variable "db_in_url" {
  type = string
}

variable "cloud_backup" {
  type = bool
}

locals {
  use_free_cluster = var.instance_size == "M0"
  cluster = try(mongodbatlas_cluster.project_cluster_free[0], mongodbatlas_cluster.project_cluster[0])
  container_id = local.cluster.container_id
}
resource "mongodbatlas_cluster" "project_cluster_free" {
  count = local.use_free_cluster ? 1 : 0
  project_id = var.project_id
  name       = var.cluster_name

  provider_name               = "TENANT"
  backing_provider_name       = "AWS"
  provider_region_name        = var.region
  provider_instance_size_name = var.instance_size
}

resource "mongodbatlas_cluster" "project_cluster" {
  count = local.use_free_cluster ? 0 : 1
  project_id   = var.project_id
  name         = var.cluster_name
  cloud_backup = var.cloud_backup
  cluster_type = "REPLICASET"
  replication_specs {
    num_shards = 1
    regions_config {
      region_name     = var.region
      electable_nodes = 3
      priority        = 7
      read_only_nodes = 0
    }
  }
  auto_scaling_disk_gb_enabled = false
  mongo_db_major_version       = "5.0"

  # Provider Settings "block"
  provider_name               = "AWS"
  disk_size_gb                = 10
  provider_instance_size_name = var.instance_size
}

resource "mongodbatlas_database_user" "mongo-user" {
  auth_database_name = "admin"
  username           = var.mongo_user
  password           = var.mongo_password
  project_id         = var.project_id
  roles {
    role_name     = "readWriteAnyDatabase"
    database_name = "admin" # The database name and collection name need not exist in the cluster before creating the user.
  }
  roles {
    role_name = "atlasAdmin"
    database_name = "admin"
  }
  
  labels {
    key   = "name"
    value = var.cluster_name
  }
}

output "info" {
  sensitive = true
  value = {
    standard_srv = local.cluster.connection_strings[0].standard_srv
    mongo_url = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(local.cluster.srv_address, "mongodb+srv://", "")}/?retryWrites=true"
    mongo_username = var.mongo_user
    mongo_password = var.mongo_password
    mongo_url_with_db = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(local.cluster.srv_address, "mongodb+srv://", "")}/${var.db_in_url}?retryWrites=true"
    cluster_container_id = local.cluster.container_id
  }
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_CLUSTER_NAME = var.cluster_name
    MONGODB_ATLAS_CONTAINER_ID = local.container_id
  }
}
