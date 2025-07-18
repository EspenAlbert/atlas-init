variable = [{
  project_id = {
    type = "string"
    default = "abc"
  }
},{
  advanced_configuration = {
    type = object({"default_write_concern":"string","custom_openssl_cipher_config_tls12":"${optional(list(string))}"})
    default = {
      default_write_concern = "majority"
      custom_openssl_cipher_config_tls12 = ["TLS1_2"]
    }
  }
}]
