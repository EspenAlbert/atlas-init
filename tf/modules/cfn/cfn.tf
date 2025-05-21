locals {
  services_yaml         = file("${path.module}/assume_role_services.yaml")
  resource_actions_yaml = file("${path.module}/resource_actions.yaml")
  services              = yamldecode(local.services_yaml)
  resource_actions      = yamldecode(local.resource_actions_yaml)
  role_name             = "mongodb-atlas-cfn-${var.cfn_profile}"
  iam_policy_statement = {
    Sid      = "Original"
    Action   = local.resource_actions
    Effect   = "Allow"
    Resource = "*"
  }
  iam_policy_statement_kms = {
    Sid      = "Extra"
    Action   = ["kms:Decrypt"]
    Effect   = "Allow"
    Resource = try(aws_kms_key.this[0].arn, "invalid-arn-not-used")
  }
  iam_policy_statement_cloudwatch = {
    Sid      = "CloudwatchLogs"
    Action   = ["logs:*"]
    Effect   = "Allow"
    Resource = "*"
  }
  iam_policy_statements = var.use_kms_key ? [local.iam_policy_statement, local.iam_policy_statement_kms, local.iam_policy_statement_cloudwatch] : [local.iam_policy_statement, local.iam_policy_statement_cloudwatch]
  iam_role_policy_json = jsonencode({
    Version   = "2012-10-17"
    Statement = local.iam_policy_statements
  })
}

resource "aws_secretsmanager_secret" "cfn" {
  name                    = "cfn/atlas/profile/${var.cfn_profile}"
  description             = "Secrets for the cfn ${var.cfn_profile} profile"
  recovery_window_in_days = 0 # allow force deletion
  tags                    = var.tags
  kms_key_id              = var.use_kms_key ? aws_kms_key.this[0].arn : null
}

resource "aws_secretsmanager_secret_version" "cfn" {
  secret_id = aws_secretsmanager_secret.cfn.id
  secret_string = jsonencode({
    BaseUrl     = var.atlas_base_url
    PublicKey   = var.atlas_public_key
    PrivateKey  = var.atlas_private_key
    DebugClient = true
  })
}

data "aws_caller_identity" "this" {}

data "aws_iam_policy_document" "assume_role" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = local.services
    }
    principals {
      type        = "AWS"
      identifiers = [data.aws_caller_identity.this.arn] # Allow the terraform creator account to assume the role
    }
  }
}

resource "aws_iam_role" "execution_role" {
  name                 = local.role_name
  assume_role_policy   = data.aws_iam_policy_document.assume_role.json
  max_session_duration = 8400

  inline_policy {
    name = "ResourceTypePolicy"

    policy = local.iam_role_policy_json

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


output "info" {
  value = {
    kms_key_policy_json  = local.kms_key_policy_json
    iam_role_policy_json = local.iam_role_policy_json
  }
}
