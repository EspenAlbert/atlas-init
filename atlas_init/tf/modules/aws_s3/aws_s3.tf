variable "bucket_name" {
  type = string
}

variable "iam_role_name" {
  type = string
}

variable "name_suffix" {
  type = string
}

resource "aws_s3_bucket" "this" {
  bucket        = var.bucket_name
  force_destroy = true
}


resource "aws_iam_role_policy" "s3_access" {
  name   = "atlas_init_s3_${var.name_suffix}"
  role   = var.iam_role_name
  policy = <<EOF
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": "s3:GetBucketLocation",
      "Resource": "arn:aws:s3:::${var.bucket_name}"
    },
    {
      "Effect": "Allow",
      "Action": "s3:*",
      "Resource": "${aws_s3_bucket.this.arn}/*"
    }
  ]
}
EOF
}

output "env_vars" {
  value = {
    AWS_S3_BUCKET = var.bucket_name
  }
}
