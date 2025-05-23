provider "mongodbatlas" {
  public_key  = var.public_key
  private_key = var.private_key
}

module "cluster" {
  source = "../../module_maintainer/v3"

  cluster_name           = var.cluster_name
  cluster_type           = var.cluster_type
  mongo_db_major_version = var.mongo_db_major_version
  project_id             = var.project_id
  replication_specs_new  = var.replication_specs_new
  tags                   = var.tags
}

output "mongodb_connection_strings" {
  description = "new connection strings desc"
  value = module.cluster.mongodb_connection_strings
}

output "with_desc" {
  value = "with_desc"
  description = "description new"
}
