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
  cluster          = try(mongodbatlas_advanced_cluster.project_cluster_free[0], mongodbatlas_advanced_cluster.project_cluster[0])
  container_id     = one(values(local.cluster.replication_specs[0].container_id))
  mongodb_url      = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(local.cluster.connection_strings.standard_srv, "mongodb+srv://", "")}/?retryWrites=true"
}
resource "mongodbatlas_advanced_cluster" "project_cluster_free" {
  count        = local.use_free_cluster ? 1 : 0
  project_id   = var.project_id
  name         = var.cluster_name
  cluster_type = "REPLICASET"

  replication_specs = [{
    region_configs = [{
      auto_scaling = {
        disk_gb_enabled = false
      }
      priority              = 7
      provider_name         = "TENANT"
      backing_provider_name = "AWS"
      region_name           = var.region
      electable_specs = {
        instance_size = var.instance_size
      }
    }]
  }]
}

resource "mongodbatlas_advanced_cluster" "project_cluster" {
  count          = local.use_free_cluster ? 0 : 1
  project_id     = var.project_id
  name           = var.cluster_name
  backup_enabled = var.cloud_backup
  cluster_type   = "REPLICASET"

  replication_specs = [{
    region_configs = [{
      priority      = 7
      provider_name = "AWS"
      region_name   = var.region
      electable_specs = {
        node_count    = 3
        instance_size = var.instance_size
        disk_size_gb  = 10
      }
    }]
  }]
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
    role_name     = "atlasAdmin"
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
    standard_srv         = local.cluster.connection_strings.standard_srv
    mongo_url            = local.mongodb_url
    mongo_username       = var.mongo_user
    mongo_password       = var.mongo_password
    mongo_url_with_db    = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(local.cluster.connection_strings.standard_srv, "mongodb+srv://", "")}/${var.db_in_url}?retryWrites=true"
    cluster_container_id = local.container_id
  }
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_CLUSTER_NAME = var.cluster_name
    MONGODB_ATLAS_CONTAINER_ID = local.container_id
    MONGODB_URL                = local.mongodb_url
  }
}
