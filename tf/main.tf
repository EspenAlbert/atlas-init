terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = "1.4.3"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    local = {
      source = "hashicorp/local"
      version = "2.4.1"
    }
    http = {
      source = "hashicorp/http"
      version = "3.4.2"
    }
  }
}

provider "mongodbatlas" {
  public_key = var.atlas_public_key
  private_key  = var.atlas_private_key
  base_url = var.atlas_base_url
}
provider "aws" {
  region     = var.aws_region
  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias = "cfn"
  region = var.cfn_config.region
  default_tags {
    tags = local.tags
  }
}

locals {
  tags = {
      Name = var.project_name
      Team = "api-x-integrations"
      Owner = "terraform-atlas-init"
    }
  use_aws_vpc = var.use_private_link
}

module "cfn" {
  source = "./modules/cfn"

  count = var.cfn_config.profile != "" ? 1 : 0
  providers = {
    aws = aws.cfn
  }
  atlas_base_url = var.atlas_base_url
  atlas_public_key = var.atlas_public_key
  atlas_private_key = var.atlas_private_key
  cfn_profile = var.cfn_config.profile
}

module "cluster" {
  source = "./modules/cluster"
  count = var.cluster_config.name != "" ? 1 : 0

  mongo_user = random_password.username.result
  mongo_password = random_password.password.result
  project_id = mongodbatlas_project.project.id
  cluster_name = var.cluster_config.name
  region = var.aws_region
  db_in_url = var.cluster_config.database_in_url
  instance_size = var.cluster_config.instance_size
}

module "aws_vpc" {
  source = "./modules/aws_vpc"

  count = local.use_aws_vpc ? 1 : 0
  aws_region = var.aws_region

}

module "vpc_privatelink" {
  source = "./modules/vpc_privatelink"

  count = var.use_private_link ? 1 : 0

  project_id = mongodbatlas_project.project.id
  subnet_ids = module.aws_vpc[0].info.subnet_ids
  security_group_ids = module.aws_vpc[0].info.security_group_ids
  vpc_id = module.aws_vpc[0].info.vpc_id
}
