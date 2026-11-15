# VPC without a NAT gateway (it would bill per hour): public subnets for the ALB, private subnets for tasks and data,
# and VPC endpoints so private tasks reach ECR, logs, S3, SSM and Bedrock without any internet route.
resource "aws_vpc" "main" {
  cidr_block           = "10.30.0.0/16"
  enable_dns_hostnames = true
  enable_dns_support   = true
  tags                 = { Name = local.name }
}

resource "aws_internet_gateway" "igw" { vpc_id = aws_vpc.main.id }

resource "aws_subnet" "public" {
  count                   = 2
  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(aws_vpc.main.cidr_block, 8, count.index)
  availability_zone       = local.azs[count.index]
  map_public_ip_on_launch = true
  tags                    = { Name = "${local.name}-public-${count.index}" }
}

resource "aws_subnet" "private" {
  count             = 2
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, 10 + count.index)
  availability_zone = local.azs[count.index]
  tags              = { Name = "${local.name}-private-${count.index}" }
}

# Sandbox subnet: no route anywhere except inside the VPC (plus the S3 gateway endpoint for image layers).
resource "aws_subnet" "sandbox" {
  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(aws_vpc.main.cidr_block, 8, 20)
  availability_zone = local.azs[0]
  tags              = { Name = "${local.name}-sandbox" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.igw.id
  }
}

resource "aws_route_table_association" "public" {
  count          = 2
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table" "private" { vpc_id = aws_vpc.main.id }

resource "aws_route_table_association" "private" {
  count          = 2
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table" "sandbox" { vpc_id = aws_vpc.main.id }

resource "aws_route_table_association" "sandbox" {
  subnet_id      = aws_subnet.sandbox.id
  route_table_id = aws_route_table.sandbox.id
}

resource "aws_security_group" "endpoints" {
  name   = "${local.name}-endpoints"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }
}

locals {
  interface_endpoints = ["ecr.api", "ecr.dkr", "logs", "ssm", "bedrock-runtime"]
}

resource "aws_vpc_endpoint" "interface" {
  for_each            = toset(local.interface_endpoints)
  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.region}.${each.key}"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.endpoints.id]
  private_dns_enabled = true
}

# S3 gateway endpoint for the app (documents) and the sandbox (ECR image layers only).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id, aws_route_table.sandbox.id]
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "EcrLayers"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject"]
        Resource  = ["arn:aws:s3:::prod-${var.region}-starport-layer-bucket/*"]
      },
      {
        Sid       = "Documents"
        Effect    = "Allow"
        Principal = "*"
        Action    = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"]
        Resource  = [aws_s3_bucket.documents.arn, "${aws_s3_bucket.documents.arn}/*"]
      }
    ]
  })
}
