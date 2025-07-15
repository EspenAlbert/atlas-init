variable "electable" {
  type = object({
    disk_size_gb = optional(number)
    regions = optional(list(object({
      cloud_provider = optional(string)
      name           = optional(string)
      node_count     = optional(number)
    })))
  })
  nullable = true
  default  = null
}

variable "auto_scaling_compute" {
  type = object({
    min_size = optional(string)
    max_size = optional(string)
  })
  nullable = true
  default  = null
}

variable "default_instance_size" {
  type     = string
  nullable = true
  default  = null
}
