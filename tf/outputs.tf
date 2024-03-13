locals {
  vpc_privatelink = try(module.vpc_privatelink[0], {
    info={}
    env_vars={}
    }
  )
  tf_cli_config_file="${path.module}/dev.tfrc"
  env_vars = {
    TF_CLI_CONFIG_FILE=abspath(local.tf_cli_config_file)
    AWS_PROFILE=var.aws_profile
    MONGODB_ATLAS_BASE_URL="https://cloud-dev.mongodb.com/"
    MONGODB_ATLAS_PUBLIC_KEY=var.atlas_public_key
    MONGODB_ATLAS_PRIVATE_KEY=var.atlas_private_key
    MONGODB_ATLAS_PROJECT_ID=mongodbatlas_project.project.id
    MONGODB_ATLAS_ORG_ID=var.org_id
    
    # atlas-cli
    MONGODB_ATLAS_OPS_MANAGER_URL="https://cloud-dev.mongodb.com/"
    # MCLI_OPS_MANAGER_URL="https://cloud-dev.mongodb.com/"
    # MCLI_PUBLIC_API_KEY=var.atlas_public_key
    # MCLI_PRIVATE_API_KEY=var.atlas_private_key
    # MCLI_PROJECT_ID=mongodbatlas_project.project.id
    # MCLI_ORG_ID=var.org_id
    # MCLI_CLIENT_ID="0oadn4hoajpzxeSEy357"
    MCLI_SKIP_UPDATE_CHECK="yes"

    # used by cfn
    MONGODB_ATLAS_PROFILE=var.your_name_lower
    PROJECT_NAME=var.project_name
    TF_ACC=1
  }
  env_vars_merged = merge(local.env_vars, local.vpc_privatelink.env_vars)
  env_vars_str = join("\n", [for key, value in local.env_vars_merged: "${key}=${value}"])
}

output "project_name" {
  value = mongodbatlas_project.project.name
}
output "project_id" {
  value = mongodbatlas_project.project.id
}
output "cluster_info" {
  value = try(module.cluster[0].info, {})
  sensitive = true
}

output "aws_networking" {
  value = {
    subnet_ids = local.subnet_ids
    security_group_ids = local.security_group_ids
    vpc_id             = local.vpc_id
  }
}

output "vpc_privatelink_info" {
  value = try(module.vpc_privatelink[0].info, {})
}

output "env_vars" {
  value = local.env_vars_merged
}

output "env_vars_dotfile" {
  value = local.env_vars_str
}
resource "local_file" "foo" {
  content  = local.env_vars_str
  filename = "${path.module}/.env-generated"
}