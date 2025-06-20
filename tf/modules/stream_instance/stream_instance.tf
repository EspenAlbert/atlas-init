variable "project_id" {
  type = string
}
variable "instance_name" {
  type = string
}

resource "mongodbatlas_stream_instance" "test" {
  project_id    = var.project_id
  instance_name = var.instance_name
  data_process_region = {
    region         = "VIRGINIA_USA"
    cloud_provider = "AWS"
  }
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_STREAM_INSTANCE_ID   = mongodbatlas_stream_instance.test.id
    MONGODB_ATLAS_STREAM_INSTANCE_NAME = var.instance_name
  }
}
