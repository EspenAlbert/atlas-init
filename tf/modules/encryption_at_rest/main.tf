variable "atlas_regions" {
  type    = list(string)
  default = ["US_EAST_1"]
}

variable "kms_key_id" {
  type = string
}
variable "project_id" {
  type = string
}

variable "atlas_role_id" {
  type = string
}

resource "mongodbatlas_encryption_at_rest" "this" {
  project_id = var.project_id
  dynamic "aws_kms_config" {
    for_each = var.atlas_regions
    content {
      enabled                = true
      customer_master_key_id = var.kms_key_id
      region                 = aws_kms_config.value
      role_id                = var.atlas_role_id

    }
  }
}
