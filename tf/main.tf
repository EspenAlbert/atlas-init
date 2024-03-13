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
  }
}
provider "aws" {
  region     = var.aws_region
  profile = var.aws_profile

  default_tags {
    tags = local.tags
  }
}

provider "aws" {
  alias = "cfn"
  region = var.aws_region_cfn_secret
  profile = var.aws_profile

  default_tags {
    tags = local.tags
  }
}
resource "random_password" "password" {
  length  = 12
  special = false
}

resource "random_password" "username" {
  length  = 12
  special = false
}

module "cluster" {
  source = "./modules/cluster"
  count = var.use_cluster ? 1 : 0

  mongo_user = random_password.username.result
  mongo_password = random_password.password.result
  project_id = mongodbatlas_project.project.id
  cluster_name = var.your_name_lower
  region = var.aws_region
  db_in_url = var.db_in_url
  instance_size = var.instance_size
}


locals {
  tags = {
      Name = "espen-example-tf"
      Team = "api-x-integrations"
    }
}

resource "aws_secretsmanager_secret" "cfn" {
  provider = aws.cfn
  name = "cfn/atlas/profile/${var.your_name_lower}"
  recovery_window_in_days = 0 # allow force deletion
}
resource "aws_secretsmanager_secret_version" "cfn" {
  provider = aws.cfn
  secret_id     = aws_secretsmanager_secret.cfn.id
  secret_string = jsonencode({
    BaseUrl="https://cloud-dev.mongodb.com/"
    PublicKey=var.atlas_public_key
    PrivateKey=var.atlas_private_key
  })
}

resource "mongodbatlas_project" "project" {
  name   = var.project_name
  org_id = var.org_id
}

resource "mongodbatlas_project_ip_access_list" "mongo-access" {
  project_id = mongodbatlas_project.project.id
  cidr_block = "0.0.0.0/0"
}

module "vpc_privatelink" {
  source = "./modules/vpc_privatelink"

  count = var.use_private_link ? 1 : 0

  project_id = mongodbatlas_project.project.id
  subnet_ids = local.subnet_ids
  security_group_ids = local.security_group_ids
  vpc_id = local.vpc_id
}
