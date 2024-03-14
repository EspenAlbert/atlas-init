terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.4.3"
    }
  }
  required_version = ">= 1.0"
}

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
resource "mongodbatlas_cluster" "project_cluster" {
  project_id = var.project_id
  name       = var.cluster_name

  provider_name               = "TENANT"
  backing_provider_name       = "AWS"
  provider_region_name        = replace(upper(var.region), "-", "_")
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
    standard_srv = mongodbatlas_cluster.project_cluster.connection_strings[0].standard_srv
    mongo_url = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(mongodbatlas_cluster.project_cluster.srv_address, "mongodb+srv://", "")}/?retryWrites=true"
    mongo_username = var.mongo_user
    mongo_password = var.mongo_password
    mongo_url_with_db = "mongodb+srv://${var.mongo_user}:${var.mongo_password}@${replace(mongodbatlas_cluster.project_cluster.srv_address, "mongodb+srv://", "")}/${var.db_in_url}?retryWrites=true"

  }
}