variable "atlas_public_key" {
  type = string
}

variable "atlas_private_key" {
  type = string
}

variable "atlas_base_url" {
  type = string
  default = "https://cloud-dev.mongodb.com/"
}

variable "org_id" {
  type = string
}

variable "aws_region" {
  type = string
  default = "us-east-1"
}

variable "project_name" {
  type = string
  validation {
    condition     = length(var.project_name) < 24
    error_message = "Mongo Project Name must be less than 24 characters."
  }
}

variable "out_dir" {
  type = string
}

variable "cfn_config" {
  type = object({
    profile = string
    region = string
  })
  default = {
    profile = ""
    region = "eu-west-1"
  }
}

variable "cluster_config" {
  type = object({
    name = string
    instance_size = string
    database_in_url = string
  })

  default = {
    name =  ""
    instance_size = "M0"
    database_in_url = "default"  
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
  type = bool
  default = false
}

variable "use_vpc_peering" {
  type = bool
  default = false
  
}

variable "use_project_extra" {
  type = bool
  default = false
}


variable "extra_env_vars" {
  default = {}
  type = map(string)
  sensitive = true
}