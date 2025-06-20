resource "random_password" "password" {
  length  = 12
  special = false
}

resource "random_password" "username" {
  length  = 12
  special = false
}

data "http" "myip" {
  count = var.use_project_myip ? 1 : 0
  url   = "https://ipv4.icanhazip.com"
}

data "http" "last_provider_version" {
  url = "https://api.github.com/repos/mongodb/terraform-provider-mongodbatlas/releases/latest"

  lifecycle {
    postcondition {
      condition     = contains([200], self.status_code)
      error_message = "Failed to get last version"
    }
  }

}

locals {
  release_response      = jsondecode(data.http.last_provider_version.response_body)
  last_provider_version = trimprefix(local.release_response.tag_name, "v")
  mongodb_username      = random_password.username.result
}

resource "mongodbatlas_project" "project" {
  name   = var.project_name
  org_id = var.org_id

  tags                      = local.tags
  region_usage_restrictions = var.is_mongodbgov_cloud ? "GOV_REGIONS_ONLY" : null
  project_owner_id          = length(var.user_id) > 0 ? var.user_id : null
}

resource "mongodbatlas_project_ip_access_list" "mongo-access" {
  count      = var.use_project_myip ? 1 : 0
  project_id = mongodbatlas_project.project.id
  cidr_block = "${chomp(data.http.myip[0].response_body)}/32"
}

data "mongodbatlas_atlas_user" "this" {
  count   = length(var.user_id) > 0 ? 1 : 0
  user_id = var.user_id
}
