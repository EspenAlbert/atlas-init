locals {
  modules_info = {
    vpc_privatelink = try(module.vpc_privatelink[0].info, {})
    cluster = try(module.cluster[0].info, {})
    aws_vpc = try(module.aws_vpc[0].info, {})
    stream_instance = try(module.stream_instance[0].info, {})
  }

  modules_env_vars = {
    vpc_privatelink = try(module.vpc_privatelink[0].env_vars, {})
    cluster = try(module.cluster[0].env_vars, {})
    aws_vpc = try(module.aws_vpc[0].env_vars, {})
    stream_instance = try(module.stream_instance[0].env_vars, {})
  }
  modules_env_vars_flat = merge([for name, env_vars in local.modules_env_vars: env_vars]...)
  project_id = mongodbatlas_project.project.id
  env_vars = {
    MONGODB_ATLAS_BASE_URL=var.atlas_base_url
    MONGODB_ATLAS_PUBLIC_KEY=var.atlas_public_key
    MONGODB_ATLAS_PRIVATE_KEY=var.atlas_private_key
    MONGODB_ATLAS_PROJECT_ID=local.project_id
    MONGODB_ATLAS_ORG_ID=var.org_id
    MONGODB_ATLAS_LAST_VERSION=local.last_provider_version
    
    # atlas-cli
    MONGODB_ATLAS_OPS_MANAGER_URL=var.atlas_base_url
    MCLI_OPS_MANAGER_URL=var.atlas_base_url
    MCLI_PUBLIC_API_KEY=var.atlas_public_key
    MCLI_PRIVATE_API_KEY=var.atlas_private_key
    MCLI_PROJECT_ID=local.project_id
    MCLI_ORG_ID=var.org_id
    MCLI_SKIP_UPDATE_CHECK="yes"

    # used by cfn
    PROJECT_NAME=var.project_name
    MONGODB_ATLAS_PROFILE=var.cfn_config.profile
    TF_ACC=1
  }
  

  env_vars_merged = merge(local.env_vars, local.modules_env_vars_flat, var.extra_env_vars)
  env_vars_str = join("\n", [for key, value in local.env_vars_merged: "${key}=${value}"])
}

output "links" {
  value = {
    org_url = "${var.atlas_base_url}v2#/org/${var.org_id}/projects"
  }
}

output "modules_info" {
  value = local.modules_info
  sensitive = true
}
output "modules_env_vars" {
  value = local.modules_env_vars
  sensitive = true
}

output "env_vars" {
  value = local.env_vars_merged
  sensitive = true
}

output "env_vars_dotfile" {
  value = local.env_vars_str
  sensitive = true
}
resource "local_file" "foo" {
  content  = local.env_vars_str
  filename = "${trimsuffix(var.out_dir, "/")}/.env-generated"
}

output "aws_regions" {
  value = {
    default = var.aws_region
    cfn = var.cfn_config.region
  }
}

output "last_provider_version" {
  value = local.last_provider_version
}
