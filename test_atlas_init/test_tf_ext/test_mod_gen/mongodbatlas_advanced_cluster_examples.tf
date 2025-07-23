# example1 - main
module "mongodbatlas_advanced_cluster" {
  source = "../.."

  project_id = var.project_id
  electable = {
    regions = [
      {
        provider_name = "AWS"
        name          = "US_EAST_1"
        node_count    = 3
      }
    ]
    disk_size_gb = 50
  }
}

# example1 - variables
variable "project_id" {
  type = string
}

# example1 - versions

terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "~> 1.26"
    }
  }
  required_version = ">= 1.8"
}
