locals {
  account_principal = {
    AWS = var.aws_account_id
  }
  kms_secretsmanager_condition = {
    StringEquals = {
      "kms:CallerAccount" = var.aws_account_id
      "kms:ViaService"    = "secretsmanager.${var.aws_region}.amazonaws.com"
    }
  }
  kms_key_policy_json = jsonencode({
    Version = "2012-10-17",
    Statement = [
      {
        Sid       = "Enable IAM User Permissions",
        Effect    = "Allow",
        Principal = local.account_principal,
        Action    = "kms:*",
        Resource  = "*"
      },
      {
        Sid    = "Enable IAM User Permissions for Role",
        Effect = "Allow",
        Principal = {
          AWS = "*"
        }
        Action   = "kms:Decrypt",
        Resource = "*"
        Condition = {
          StringEquals = {
            "aws:PrincipalArn" = "arn:aws:iam::${var.aws_account_id}:role/${local.role_name}"
          }
        }
      },
      # { useful to check our example guide
      #   "Sid" : "Allow access through AWS Secrets Manager for all principals in the account that are authorized to use AWS Secrets Manager",
      #   "Effect" : "Allow",
      #   # "Principal" : { "AWS" : [aws_iam_role.execution_role.arn] },
      #   "Principal" : { "AWS" : "*" },
      #   "Action" : [
      #     "kms:Decrypt",
      #   ],
      #   "Resource" : "*",
      #   "Condition" : local.kms_secretsmanager_condition
      # },
    ]
  })
}
resource "aws_kms_key" "this" {
  count                   = var.use_kms_key ? 1 : 0
  description             = "KMS key for ${var.cfn_profile}"
  deletion_window_in_days = 7
  policy                  = local.kms_key_policy_json
}
