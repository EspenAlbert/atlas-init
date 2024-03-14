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

resource "mongodbatlas_project" "project" {
  name   = var.project_name
  org_id = var.org_id
}

resource "mongodbatlas_project_ip_access_list" "mongo-access" {
  project_id = mongodbatlas_project.project.id
  cidr_block = "${chomp(data.http.myip.response_body)}/32"
}