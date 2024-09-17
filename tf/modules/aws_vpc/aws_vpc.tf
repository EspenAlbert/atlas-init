variable "aws_region" {
  type = string
}

locals {
  cidr_block = "10.0.0.0/16"
}
resource "aws_vpc" "this" {
  cidr_block           = local.cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true
}

resource "aws_internet_gateway" "ig_east" {
  vpc_id = aws_vpc.this.id
}

resource "aws_route" "route_east" {
  route_table_id         = aws_vpc.this.main_route_table_id
  destination_cidr_block = "0.0.0.0/0"
  gateway_id             = aws_internet_gateway.ig_east.id
}

resource "aws_subnet" "subnet_a" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.0.1.0/24"
  map_public_ip_on_launch = true
  availability_zone       = "${var.aws_region}a"
}

resource "aws_subnet" "subnet_b" {
  vpc_id                  = aws_vpc.this.id
  cidr_block              = "10.0.2.0/24"
  map_public_ip_on_launch = false
  availability_zone       = "${var.aws_region}b"
}

resource "aws_security_group" "this" {
  name_prefix = "default-"
  description = "Default security group for all instances in vpc"
  vpc_id      = aws_vpc.this.id
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "tcp"
    cidr_blocks = [
      "0.0.0.0/0",
    ]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}

output "info" {
  value = {
    subnet_ids          = [aws_subnet.subnet_a.id, aws_subnet.subnet_b.id]
    security_group_ids  = [aws_security_group.this.id]
    vpc_id              = aws_vpc.this.id
    main_route_table_id = aws_vpc.this.main_route_table_id
    vpc_cidr_block      = local.cidr_block
  }
}

output "env_vars" {
  value = {
    AWS_VPC_ID            = aws_vpc.this.id
    AWS_VPC_CIDR_BLOCK    = local.cidr_block
    AWS_SECURITY_GROUP_ID = aws_security_group.this.id
    AWS_SUBNET_ID         = aws_subnet.subnet_a.id
  }
}
