module "cluster" {
  source                 = "../.."

  project_id             = var.project_id
  name                   = "single-region"
  mongo_db_major_version = "8.0"
  aws_regions = {
    "US_EAST_1" = 3
  }
  auto_scaling = {
    disk_gb_enabled           = true
    compute_enabled           = true
    compute_max_instance_size = "M60"
    compute_min_instance_size = "M30"
  }
}
