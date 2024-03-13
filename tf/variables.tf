variable "aws_profile" {
  type = string
}
variable "your_name_lower" {
  type = string
}

variable "atlas_public_key" {
  type = string
}

variable "atlas_private_key" {
  type = string
}

variable "org_id" {
  # https://cloud.mongodb.com/v2#/org/5e91e686a00db22839299d64/projects
  type = string
}

variable "project_name" {
  # follow convention env+namespace whenever possible
  type = string
  validation {
    condition     = length(var.project_name) < 24
    error_message = "Mongo Project Name must be less than 24 characters."
  }
}

variable "instance_size" {
  # https://docs.atlas.mongodb.com/reference/amazon-aws/
  default = "M0"
}

variable "db_in_url" {
  default = "default"
  type    = string
}

variable "use_private_link" {
  type = bool
  default = false
}

variable "aws_region" {
  type = string
  default = "us-east-1"
}

variable "aws_region_cfn_secret" {
  type = string
  default = "eu-south-2"
}

variable "use_cluster" {
  default = false
  type = bool
}
