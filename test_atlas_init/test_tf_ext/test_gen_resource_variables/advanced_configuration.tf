variable "advanced_configuration" {
  type = object({
    change_stream_options_pre_and_post_images_expire_after_seconds = optional(number)
    custom_openssl_cipher_config_tls12                             = optional(list(string), ["TLS1_2"])
    default_max_time_ms                                            = optional(number)
    default_write_concern                                          = string
    fail_index_key_too_long                                        = optional(bool)
    javascript_enabled                                             = optional(bool, false)
    minimum_enabled_tls_protocol                                   = optional(string)
    no_table_scan                                                  = optional(bool)
    oplog_min_retention_hours                                      = optional(number)
    oplog_size_mb                                                  = optional(number)
    sample_refresh_interval_bi_connector                           = optional(number)
    sample_size_bi_connector                                       = optional(number)
    tls_cipher_config_mode                                         = optional(string, "DEFAULT")
    transaction_lifetime_limit_seconds                             = optional(number)
  })
  nullable = true
  default = {
    custom_openssl_cipher_config_tls12 = ["TLS1_2"]
    javascript_enabled                 = false
    tls_cipher_config_mode             = "DEFAULT"
  }
}
