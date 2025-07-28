variable "mongodbatlas_cloud_backup_schedule" {
  type = object({
    auto_export_enabled                      = optional(bool)
    cluster_name                             = string
    id                                       = optional(string)
    project_id                               = string
    reference_hour_of_day                    = optional(number)
    reference_minute_of_hour                 = optional(number)
    restore_window_days                      = optional(number)
    update_snapshots                         = optional(bool)
    use_org_and_group_names_in_export_prefix = optional(bool)
    copy_settings = optional(object({
      cloud_provider     = optional(string)
      frequencies        = optional(list(string))
      region_name        = optional(string)
      should_copy_oplogs = optional(bool)
      zone_id            = optional(string)
    }))
    export = optional(object({
      export_bucket_id = optional(string)
      frequency_type   = optional(string)
    }))
    policy_item_daily = optional(object({
      frequency_interval = number
      retention_unit     = string
      retention_value    = number
    }))
    policy_item_hourly = optional(object({
      frequency_interval = number
      retention_unit     = string
      retention_value    = number
    }))
    policy_item_monthly = optional(object({
      frequency_interval = number
      retention_unit     = string
      retention_value    = number
    }))
    policy_item_weekly = optional(object({
      frequency_interval = number
      retention_unit     = string
      retention_value    = number
    }))
    policy_item_yearly = optional(object({
      frequency_interval = number
      retention_unit     = string
      retention_value    = number
    }))
  })
  nullable = true
  default  = null
}
