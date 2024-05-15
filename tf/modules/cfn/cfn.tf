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

variable "tags" {
  type = map(string)
}

terraform {
  required_providers {
    aws = {
      source = "hashicorp/aws"
    }
  }
}

locals {
  services_yaml         = file("${path.module}/assume_role_services.yaml")
  resource_actions_yaml = file("${path.module}/resource_actions.yaml")
  services              = yamldecode(local.services_yaml)
  resource_actions      = yamldecode(local.resource_actions_yaml)
}

resource "aws_secretsmanager_secret" "cfn" {
  name                    = "cfn/atlas/profile/${var.cfn_profile}"
  recovery_window_in_days = 0 # allow force deletion
  tags                    = var.tags
}
resource "aws_secretsmanager_secret_version" "cfn" {
  secret_id = aws_secretsmanager_secret.cfn.id
  secret_string = jsonencode({
    BaseUrl    = var.atlas_base_url
    PublicKey  = var.atlas_public_key
    PrivateKey = var.atlas_private_key
  })
}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = local.services
    }
  }
}

resource "aws_iam_role" "execution_role" {
  name                 = "cfn-execution-role-${var.cfn_profile}"
  assume_role_policy   = data.aws_iam_policy_document.assume_role.json
  max_session_duration = 8400

  inline_policy {
    name = "ResourceTypePolicy"

    policy = jsonencode({
      Version = "2012-10-17"
      Statement = [
        {
          Action   = local.resource_actions
          Effect   = "Allow"
          Resource = "*"
        },
      ]
    })

  }
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_PROFILE         = var.cfn_profile
    MONGODB_ATLAS_PUBLIC_API_KEY  = var.atlas_public_key
    MONGODB_ATLAS_PRIVATE_API_KEY = var.atlas_private_key
    # cfn-e2e
    MONGODB_ATLAS_SECRET_PROFILE = var.cfn_profile
    CFN_EXAMPLE_EXECUTION_ROLE   = aws_iam_role.execution_role.arn
  }
}
