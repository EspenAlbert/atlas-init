terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.19.0"
    }
  }
}

variable "org_id" {
  type = string
}

variable "id_suffix" {
  description = "used as suffix in project-name, description of the api key, and in the team name, should not change"
  type        = string
}

resource "mongodbatlas_api_key" "project_key" {
  org_id      = var.org_id
  role_names  = ["ORG_MEMBER"]
  description = "cfn-contract-test-${var.id_suffix}"
}

data "mongodbatlas_atlas_users" "this" {
  org_id = var.org_id
}

locals {
  project_user_username = data.mongodbatlas_atlas_users.this.results[0].username
}
resource "mongodbatlas_team" "project_team" {
  org_id    = var.org_id
  name      = "cfn-contract-test-${var.id_suffix}"
  usernames = [local.project_user_username]
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_TEAM_ID        = mongodbatlas_team.project_team.team_id
    MONGODB_ATLAS_ORG_API_KEY_ID = mongodbatlas_api_key.project_key.api_key_id
  }
}
