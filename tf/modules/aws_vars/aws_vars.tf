variable "aws_access_key_id" {
  type = string
}
variable "aws_secret_access_key" {
  type = string
}
variable "aws_region" {
  type = string
}

output "env_vars" {
  value = {
    AWS_CUSTOMER_MASTER_KEY_ID = "dummy"
    AWS_ACCESS_KEY_ID          = var.aws_access_key_id
    AWS_SECRET_ACCESS_KEY      = var.aws_secret_access_key
    AWS_REGION                 = var.aws_region
    AWS_REGION_LOWERCASE       = var.aws_region
    AWS_REGION_UPPERCASE       = replace(upper(var.aws_region), "-", "_")
  }
}
