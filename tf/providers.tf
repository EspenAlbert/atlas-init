terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = ">=1.33"
    }
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    local = {
      source  = "hashicorp/local"
      version = "2.4.1"
    }
    http = {
      source  = "hashicorp/http"
      version = "3.4.2"
    }
  }
}

provider "mongodbatlas" {
  public_key  = var.atlas_public_key
  private_key = var.atlas_private_key
  base_url    = var.atlas_base_url
  # is_mongodbgov_cloud = var.is_mongodbgov_cloud the base_url takes preference in provider.go
}
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = local.tags
  }
}
provider "aws" {
  alias  = "no_tags"
  region = var.aws_region
}

provider "aws" {
  alias  = "cfn"
  region = var.cfn_config.region
}
