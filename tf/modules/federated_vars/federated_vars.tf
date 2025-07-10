variable "federated_settings_id" {
  type = string
  validation {
    condition     = length(var.federated_settings_id) > 0
    error_message = "missing federate_settings_id"
  }
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
  org_id                 = var.org_id
}

output "info" {
  value = {
    federation_org_url = "${var.base_url}v2#/federation/${var.federated_settings_id}/organizations"
  }
}


output "env_vars" {
  value = {
    MONGODB_ATLAS_FEDERATION_SETTINGS_ID = var.federated_settings_id
    MONGODB_ATLAS_FEDERATED_ORG_ID       = var.org_id
    MONGODB_ATLAS_FEDERATED_GROUP_ID     = var.project_id
    MONGODB_ATLAS_FEDERATED_IDP_ID       = data.mongodbatlas_federated_settings_org_config.current.identity_provider_id # 20 character legacy needed for PATCH on org
    # MONGODB_ATLAS_FEDERATED_IDP_ID = data.mongodbatlas_federated_settings_org_config.current.okta_idp_id # used for org PATCH
    MONGODB_ATLAS_FEDERATED_SETTINGS_ASSOCIATED_DOMAIN = try(data.mongodbatlas_federated_settings_org_config.current.domain_allow_list[0], "no-domain-set-by-atlas-init.com")
  }
}