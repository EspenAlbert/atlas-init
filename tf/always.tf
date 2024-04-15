resource "random_password" "password" {
  length  = 12
  special = false
}

resource "random_password" "username" {
  length  = 12
  special = false
}

data "http" "myip" {
  url = "https://ipv4.icanhazip.com"
}

data "http" "last_provider_version" {
  url = "https://api.github.com/repos/mongodb/terraform-provider-mongodbatlas/releases/latest"

lifecycle {
  postcondition {
    condition = contains([200], self.status_code)
    error_message = "Failed to get last version"
  }
}

}

locals {
  release_response = jsondecode(data.http.last_provider_version.response_body)
  last_provider_version = trimprefix(local.release_response.tag_name, "v")
}

resource "mongodbatlas_project" "project" {
  name   = var.project_name
  org_id = var.org_id
  lifecycle {
    ignore_changes = [ 
      tags["name"]
     ]
  }
}

resource "mongodbatlas_project_ip_access_list" "mongo-access" {
  project_id = mongodbatlas_project.project.id
  cidr_block = "${chomp(data.http.myip.response_body)}/32"
}