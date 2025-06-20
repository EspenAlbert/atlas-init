variable "atlas_vpc_cidr" {
  description = "Atlas CIDR"
  default     = "192.168.232.0/21"
  type        = string
}

variable "atlas_region" {
  type = string
}

variable "main_route_table_id" {
  type = string
}

variable "vpc_cidr_block" {
  type = string
}

variable "vpc_id" {
  type = string
}
variable "project_id" {
  type = string
}
variable "aws_account_id" {
  type = string
}

variable "skip_resources" {
  type = bool
}


resource "aws_route" "peeraccess" {
  count = var.skip_resources ? 0 : 1

  route_table_id            = var.main_route_table_id
  destination_cidr_block    = var.atlas_vpc_cidr
  vpc_peering_connection_id = mongodbatlas_network_peering.aws_atlas[0].connection_id
  depends_on                = [aws_vpc_peering_connection_accepter.peer[0]]
}

resource "mongodbatlas_network_container" "this" {
  count = var.skip_resources ? 0 : 1

  project_id       = var.project_id
  atlas_cidr_block = var.atlas_vpc_cidr
  provider_name    = "AWS"
  region_name      = var.atlas_region
}
resource "mongodbatlas_network_peering" "aws_atlas" {
  count = var.skip_resources ? 0 : 1

  accepter_region_name   = var.atlas_region
  project_id             = var.project_id
  container_id           = mongodbatlas_network_container.this[0].id
  provider_name          = "AWS"
  route_table_cidr_block = var.vpc_cidr_block
  vpc_id                 = var.vpc_id
  aws_account_id         = var.aws_account_id
}

resource "aws_vpc_peering_connection_accepter" "peer" {
  count = var.skip_resources ? 0 : 1

  vpc_peering_connection_id = mongodbatlas_network_peering.aws_atlas[0].connection_id
  auto_accept               = true
}

resource "mongodbatlas_project_ip_access_list" "test" {
  project_id = var.project_id
  cidr_block = var.vpc_cidr_block
  comment    = "cidr block for AWS VPC used by mongodbatlas_network_peering"
}

output "env_vars" {
  value = {
    AWS_ACCOUNT_ID     = var.aws_account_id
    AWS_VPC_CIDR_BLOCK = var.vpc_cidr_block
    AWS_VPC_ID         = var.vpc_id
    AWS_REGION         = var.atlas_region
  }
}
