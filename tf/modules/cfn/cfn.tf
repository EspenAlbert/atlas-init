variable "cfn_profile" {
  type = string
}
variable "atlas_public_key" {
  type = string
}

variable "atlas_private_key" {
  type = string
}

variable "atlas_base_url" {
  type = string
}

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

resource "aws_secretsmanager_secret" "cfn" {
  name = "cfn/atlas/profile/${var.cfn_profile}"
  recovery_window_in_days = 0 # allow force deletion
}
resource "aws_secretsmanager_secret_version" "cfn" {
  secret_id     = aws_secretsmanager_secret.cfn.id
  secret_string = jsonencode({
    BaseUrl=var.atlas_base_url
    PublicKey=var.atlas_public_key
    PrivateKey=var.atlas_private_key
  })
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_PROFILE = var.cfn_profile
  }
}
