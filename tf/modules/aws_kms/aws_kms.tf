variable "aws_account_id" {
  type = string
}
variable "aws_region" {
  type = string
}
variable "access_iam_role_arns" {
  type        = map(string)
  description = "static name to arn"
}

variable "key_suffix" {
  type = string
}

locals {
  kms_secretsmanager_condition = {
    StringEquals = {
      "kms:CallerAccount" = var.aws_account_id
      "kms:ViaService"    = "secretsmanager.${var.aws_region}.amazonaws.com"
    }
  }
  role_names = { for static_name, role_arn in var.access_iam_role_arns : split("/", role_arn)[length(split("/", role_arn)) - 1] => role_arn }
  kms_key_policy_statements = [
    {
      Sid    = "Enable IAM User Permissions Current AWS Account",
      Effect = "Allow",
      Principal = {
        AWS = var.aws_account_id
      },
      Action   = "kms:*",
      Resource = "*"
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

  access_roles = [for role_name, role_arn in local.role_names :
    {
      Sid    = "Enable IAM Permissions for Role ${role_name}",
      Effect = "Allow",
      Principal = {
        AWS = "*"
      }
      Action   = "kms:*",
      Resource = "*"
      Condition = {
        StringEquals = {
          "aws:PrincipalArn" = role_arn
        }
      }
    }
  ]
  kms_key_policy_json = jsonencode({
    Version   = "2012-10-17",
    Statement = concat(local.kms_key_policy_statements, local.access_roles)
  })
}
resource "aws_kms_key" "this" {
  description             = "KMS key for atlas-init ${var.key_suffix}"
  deletion_window_in_days = 7
  multi_region            = true
  policy                  = local.kms_key_policy_json
}

resource "aws_iam_role_policy" "kms_access" {
  for_each = var.access_iam_role_arns
  name     = "atlas-init-${each.key}-kms-access"
  role     = split("/", each.value)[length(split("/", each.value)) - 1]

  policy = <<-EOF
  {
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "kms:*"
        ],
        "Resource": [
          "${aws_kms_key.this.arn}"
        ]
      }
    ]
  }
  EOF
}

output "kms_key_id" {
  value = aws_kms_key.this.id
}
