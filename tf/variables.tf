variable "atlas_public_key" {
  type = string
}

variable "atlas_private_key" {
  type = string
}

variable "atlas_base_url" {
  type    = string
  default = "https://cloud-dev.mongodb.com/"
}

variable "user_id" {
  type    = string
  default = ""
}

variable "is_mongodbgov_cloud" {
  type    = bool
  default = false
}

variable "federated_settings_id" {
  type    = string
  default = ""
}

variable "org_id" {
  type = string
}

variable "aws_region" {
  type    = string
  default = "us-east-1"
}

variable "project_name" {
  type = string
  validation {
    condition     = length(var.project_name) < 24
    error_message = "Mongo Project Name must be less than 24 characters."
  }
}

variable "use_project_myip" {
  type    = bool
  default = false
}

variable "out_dir" {
  type = string
}

variable "cfn_config" {
  type = object({
    profile     = string
    region      = string
    use_kms_key = bool
  })
  default = {
    profile     = ""
    region      = "eu-west-1"
    use_kms_key = false
  }
}

variable "cluster_config" {
  type = object({
    name            = string
    instance_size   = string
    database_in_url = string
    cloud_backup    = bool
  })

  default = {
    name            = ""
    instance_size   = "M0"
    database_in_url = "default"
    cloud_backup    = false
  }
}

variable "stream_instance_config" {
  type = object({
    name = string
  })
  default = {
    name = ""
  }
}
variable "use_private_link" {
  type    = bool
  default = false
}

variable "use_vpc_peering" {
  type    = bool
  default = false

}

variable "use_project_extra" {
  type    = bool
  default = false
}

variable "use_aws_vpc" {
  type    = bool
  default = false
}
variable "extra_env_vars" {
  default   = {}
  type      = map(string)
  sensitive = true
}

variable "aws_access_key_id" {
  type    = string
  default = ""
}
variable "aws_secret_access_key" {
  type    = string
  default = ""
}

variable "use_aws_vars" {
  type    = bool
  default = false
}

variable "use_aws_s3" {
  type    = bool
  default = false
}

variable "use_federated_vars" {
  type    = bool
  default = false
}

variable "use_encryption_at_rest" {
  type    = bool
  default = false
}
