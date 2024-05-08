variable "federated_settings_id" {
    type = string
}

variable "org_id" {
  type = string
}

variable "project_id" {
  type = string
}

variable "base_url" {
  type = string
}

data "mongodbatlas_federated_settings_org_config" "current" {
    federation_settings_id = var.federated_settings_id
    org_id = var.org_id
}

output "info" {
  value = {
    federation_org_url = "${var.base_url}v2#/federation/${var.federated_settings_id}/organizations"
  }
}


output "env_vars" {
    value = {
        MONGODB_ATLAS_FEDERATION_SETTINGS_ID=var.federated_settings_id
        MONGODB_ATLAS_FEDERATED_ORG_ID=var.org_id
        MONGODB_ATLAS_FEDERATED_GROUP_ID=var.project_id
    }
  
}