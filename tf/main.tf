locals {
  tags = {
    Name  = var.project_name
    Team  = "api-x-integrations"
    Owner = "terraform-atlas-init"
  }
  use_aws_vpc        = var.use_private_link || var.use_vpc_peering || var.use_aws_vpc
  use_aws_kms        = var.use_encryption_at_rest
  use_cloud_provider = var.use_aws_s3 || var.use_encryption_at_rest
  # https://www.mongodb.com/docs/atlas/reference/amazon-aws/
  atlas_region = replace(upper(var.aws_region), "-", "_")
  use_cluster  = var.cluster_config.name != ""
  cfn_profile  = var.cfn_config.profile
}

module "cfn" {
  source = "./modules/cfn"

  count = local.cfn_profile != "" ? 1 : 0
  providers = {
    aws = aws.cfn
  }
  atlas_base_url    = var.atlas_base_url
  atlas_public_key  = var.atlas_public_key
  atlas_private_key = var.atlas_private_key
  cfn_profile       = local.cfn_profile
  tags              = local.tags
  aws_account_id    = local.aws_account_id
  use_kms_key       = var.cfn_config.use_kms_key
  aws_region        = var.cfn_config.region
}

module "cluster" {
  source = "./modules/cluster"
  count  = local.use_cluster ? 1 : 0

  mongo_user     = local.mongodb_username
  mongo_password = random_password.password.result
  project_id     = local.project_id
  cluster_name   = var.cluster_config.name
  region         = local.atlas_region
  db_in_url      = var.cluster_config.database_in_url
  instance_size  = var.cluster_config.instance_size
  cloud_backup   = var.cluster_config.cloud_backup
}

module "aws_vpc" {
  source = "./modules/aws_vpc"

  count      = local.use_aws_vpc ? 1 : 0
  aws_region = var.aws_region
}

resource "null_resource" "vpc_peering_precondition" {
  count = var.use_vpc_peering ? 1 : 0
  lifecycle {
    precondition {
      condition     = local.use_cluster == false
      error_message = "Cannot use a cluster when using vpc_peering since it will create the container_id for the project."
    }
  }
}

module "vpc_peering" {
  source = "./modules/vpc_peering"

  count               = var.use_vpc_peering ? 1 : 0
  vpc_id              = module.aws_vpc[0].info.vpc_id
  vpc_cidr_block      = module.aws_vpc[0].info.vpc_cidr_block
  main_route_table_id = module.aws_vpc[0].info.main_route_table_id
  atlas_region        = local.atlas_region
  project_id          = local.project_id
  skip_resources      = true
  aws_account_id      = local.aws_account_id
}

module "vpc_privatelink" {
  source = "./modules/vpc_privatelink"

  count = var.use_private_link ? 1 : 0

  project_id         = local.project_id
  subnet_ids         = module.aws_vpc[0].info.subnet_ids
  security_group_ids = module.aws_vpc[0].info.security_group_ids
  vpc_id             = module.aws_vpc[0].info.vpc_id
}


module "stream_instance" {
  source = "./modules/stream_instance"

  count = var.stream_instance_config.name != "" ? 1 : 0

  project_id    = local.project_id
  instance_name = var.stream_instance_config.name
}

module "project_extra" {
  source = "./modules/project_extra"

  count = var.use_project_extra ? 1 : 0

  org_id    = var.org_id
  id_suffix = local.mongodb_username

}

module "aws_vars" {
  source = "./modules/aws_vars"
  count  = var.use_aws_vars ? 1 : 0

  aws_access_key_id     = var.aws_access_key_id
  aws_secret_access_key = var.aws_secret_access_key
  aws_region            = var.aws_region
}

module "cloud_provider" {
  source = "./modules/cloud_provider"
  count  = local.use_cloud_provider ? 1 : 0

  providers = {
    aws = aws.no_tags
  }
  name_suffix = var.project_name
  project_id  = local.project_id
}

module "aws_s3" {
  source = "./modules/aws_s3"
  count  = var.use_aws_s3 ? 1 : 0

  name_suffix   = var.project_name
  bucket_name   = "atlas-init-${replace(var.project_name, "_", "-")}"
  iam_role_name = module.cloud_provider[0].iam_role_name
}

module "aws_kms" {
  source = "./modules/aws_kms"
  count  = local.use_aws_kms ? 1 : 0

  access_iam_role_arns = {
    atlas = module.cloud_provider[0].iam_role_arn
  }
  aws_account_id = local.aws_account_id
  aws_region     = var.aws_region
  key_suffix     = var.project_name
}

module "federated_vars" {
  source = "./modules/federated_vars"
  count  = var.use_federated_vars ? 1 : 0

  federated_settings_id = var.federated_settings_id
  org_id                = var.org_id
  project_id            = local.project_id
  base_url              = var.atlas_base_url
}

module "encryption_at_rest" {
  source = "./modules/encryption_at_rest"
  count  = var.use_encryption_at_rest ? 1 : 0

  project_id    = local.project_id
  atlas_role_id = module.cloud_provider[0].atlas_role_id
  kms_key_id    = module.aws_kms[0].kms_key_id
  atlas_regions = [local.atlas_region]

}
