# resource "mongodbatlas_privatelink_endpoint" "pe_east" {
#   project_id    = var.project_id
#   provider_name = "AWS"
#   region        = var.aws_region
# }
# found immediately from the region in the UI
# https://github.com/10gen/mms/blob/85ec3df92711014b17643c05a61f5c580786556c/server/conf/data-lake-endpoint-services.json

resource "aws_vpc_endpoint" "this" {
  vpc_id             = var.vpc_id
  service_name       = "com.amazonaws.vpce.us-east-1.vpce-svc-0a7247db33497082e"
  vpc_endpoint_type  = "Interface"
  subnet_ids         = var.subnet_ids
  security_group_ids = var.security_group_ids
}


output "info" {
  value = {
    # federate_db_private_endpoint_region = mongodbatlas_privatelink_endpoint_service_data_federation_online_archive.test.region
    # federate_db_private_endpoint_customer_endpoint_dns_name = mongodbatlas_privatelink_endpoint_service_data_federation_online_archive.test.customer_endpoint_dns_name
    # data_source_region = data.mongodbatlas_privatelink_endpoint_service_data_federation_online_archive.test.region
    vpc_endpoint_id = aws_vpc_endpoint.this.id
  }
}

output "env_vars" {
  value = {
    MONGODB_ATLAS_PRIVATE_ENDPOINT_ID       = aws_vpc_endpoint.this.id
    MONGODB_ATLAS_PRIVATE_ENDPOINT_DNS_NAME = aws_vpc_endpoint.this.dns_entry[0].dns_name
  }
}