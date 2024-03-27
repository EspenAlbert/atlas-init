terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.4.3"
    }
  }
  required_version = ">= 1.0"
}

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

variable "cluster_container_id" {
  type = string
}

locals {
  account_id = data.aws_caller_identity.current.account_id
}


data "aws_caller_identity" "current" {}

resource "aws_route" "peeraccess" {
  route_table_id            = var.main_route_table_id
  destination_cidr_block    = var.atlas_vpc_cidr
  vpc_peering_connection_id = mongodbatlas_network_peering.aws_atlas.connection_id
  depends_on                = [aws_vpc_peering_connection_accepter.peer]
}

resource "mongodbatlas_network_peering" "aws_atlas" {
  accepter_region_name   = var.atlas_region
  project_id             = var.project_id
  container_id           = var.cluster_container_id
  provider_name          = "AWS"
  route_table_cidr_block = var.vpc_cidr_block
  vpc_id                 = var.vpc_id
  aws_account_id         = local.account_id
}

resource "aws_vpc_peering_connection_accepter" "peer" {
  vpc_peering_connection_id = mongodbatlas_network_peering.aws_atlas.connection_id
  auto_accept               = true
}

resource "mongodbatlas_project_ip_access_list" "test" {
  project_id = var.project_id
  cidr_block = var.vpc_cidr_block
  comment    = "cidr block for AWS VPC"
}

output "env_vars" {
  value = {
    AWS_ACCOUNT_ID = local.account_id
    AWS_VPC_CIDR_BLOCK = var.vpc_cidr_block
    AWS_VPC_ID = var.vpc_id
    AWS_REGION = var.atlas_region
  }
}
