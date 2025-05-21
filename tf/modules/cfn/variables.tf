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

variable "use_kms_key" {
  type    = bool
  default = false
}

variable "aws_account_id" {
  type = string
}

variable "aws_region" {
  type = string
}