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
}

locals {
  tags = {
      Name = var.project_name
      Team = "api-x-integrations"
      Owner = "terraform-atlas-init"
    }
  use_aws_vpc = var.use_private_link || var.use_vpc_peering || var.use_aws_vpc
  # https://www.mongodb.com/docs/atlas/reference/amazon-aws/
  atlas_region = replace(upper(var.aws_region), "-", "_")
  use_cluster = var.cluster_config.name != ""
  cfn_profile = var.cfn_config.profile
}

module "cfn" {
  source = "./modules/cfn"

  count = local.cfn_profile != "" ? 1 : 0
  providers = {
    aws = aws.cfn
  }
  atlas_base_url = var.atlas_base_url
  atlas_public_key = var.atlas_public_key
  atlas_private_key = var.atlas_private_key
  cfn_profile = local.cfn_profile
  tags = local.tags
}

module "cluster" {
  source = "./modules/cluster"
  count = local.use_cluster ? 1 : 0

  mongo_user = local.mongodb_username
  mongo_password = random_password.password.result
  project_id = local.project_id
  cluster_name = var.cluster_config.name
  region = local.atlas_region
  db_in_url = var.cluster_config.database_in_url
  instance_size = var.cluster_config.instance_size
}

module "aws_vpc" {
  source = "./modules/aws_vpc"

  count = local.use_aws_vpc ? 1 : 0
  aws_region = var.aws_region
}

resource "null_resource" "vpc_peering_precondition" {
  count = var.use_vpc_peering ? 1 : 0
  lifecycle {
    precondition {
      condition = local.use_cluster == false
      error_message = "Cannot use a cluster when using vpc_peering since it will create the container_id for the project."
    }
  }
}

module "vpc_peering" {
  source = "./modules/vpc_peering"

  count = var.use_vpc_peering ? 1 : 0
  vpc_id = module.aws_vpc[0].info.vpc_id
  vpc_cidr_block = module.aws_vpc[0].info.vpc_cidr_block
  main_route_table_id = module.aws_vpc[0].info.main_route_table_id
  atlas_region = local.atlas_region
  project_id = local.project_id
  skip_resources = true
}

module "vpc_privatelink" {
  source = "./modules/vpc_privatelink"

  count = var.use_private_link ? 1 : 0

  project_id = local.project_id
  subnet_ids = module.aws_vpc[0].info.subnet_ids
  security_group_ids = module.aws_vpc[0].info.security_group_ids
  vpc_id = module.aws_vpc[0].info.vpc_id
}


module "stream_instance" {
  source = "./modules/stream_instance"

  count = var.stream_instance_config.name != "" ? 1 : 0
  
  project_id = local.project_id
  instance_name = var.stream_instance_config.name
}

module "project_extra" {
  source = "./modules/project_extra"

  count = var.use_project_extra ? 1 : 0

  org_id = var.org_id
  id_suffix = local.mongodb_username
  
}