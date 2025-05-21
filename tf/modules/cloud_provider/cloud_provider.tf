variable "project_id" {
  type = string
}

variable "name_suffix" {
  type = string
}

resource "mongodbatlas_cloud_provider_access_setup" "setup_only" {
  project_id    = var.project_id
  provider_name = "AWS"
}

resource "mongodbatlas_cloud_provider_access_authorization" "auth_role" {
  project_id = var.project_id
  role_id    = mongodbatlas_cloud_provider_access_setup.setup_only.role_id

  aws {
    iam_assumed_role_arn = aws_iam_role.aws_role.arn
  }
}


resource "aws_iam_role" "aws_role" {
  name = "mongodb-atlas-ainit-${var.name_suffix}"

  assume_role_policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "AWS": "${mongodbatlas_cloud_provider_access_setup.setup_only.aws_config[0].atlas_aws_account_arn}"
      },
      "Action": "sts:AssumeRole",
      "Condition": {
        "StringEquals": {
          "sts:ExternalId": "${mongodbatlas_cloud_provider_access_setup.setup_only.aws_config[0].atlas_assumed_role_external_id}"
        }
      }
    }
  ]
}
EOF
}


output "env_vars" {
  value = {
    IAM_ROLE_ID      = mongodbatlas_cloud_provider_access_authorization.auth_role.role_id
    AWS_IAM_ROLE_ARN = aws_iam_role.aws_role.arn
  }
}

output "iam_role_name" {
  value = aws_iam_role.aws_role.name
}

output "atlas_role_id" {
  value = mongodbatlas_cloud_provider_access_authorization.auth_role.role_id
}

output "iam_role_arn" {
  value = aws_iam_role.aws_role.arn
}