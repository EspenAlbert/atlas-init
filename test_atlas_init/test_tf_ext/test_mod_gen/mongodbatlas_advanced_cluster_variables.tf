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

variable "electable" {
  type = object({
    regions = optional(list(object({
      provider_name = optional(string)
      name          = optional(string)
      node_count    = optional(number)
    })))
    disk_size_gb = optional(number)
  })
  nullable = true
  default  = null
}
