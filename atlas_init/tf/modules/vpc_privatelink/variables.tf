variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_id" {
  type = string
}

variable "vpc_id" {
  type = string
}

variable "subnet_ids" {
  type = list(string)
}
variable "security_group_ids" {
  type = list(string)
}