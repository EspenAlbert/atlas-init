terraform {
  required_providers {
    mongodbatlas = {
      source  = "mongodb/mongodbatlas"
      version = ">=1.33"
    }
    aws = {
      source = "hashicorp/aws"
    }
  }

  required_version = ">= 1.0"
}