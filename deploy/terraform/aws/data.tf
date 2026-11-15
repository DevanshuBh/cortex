# Postgres (RDS, pgvector), Redis (ElastiCache, non-cluster for Celery), Neo4j Community on EC2, S3 documents.
resource "aws_security_group" "app" {
  name   = "${local.name}-app"
  vpc_id = aws_vpc.main.id
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [aws_vpc.main.cidr_block] # nothing leaves the VPC; endpoints cover the AWS APIs
  }
  egress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id]
  }
  ingress {
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }
}

resource "aws_security_group" "data" {
  name   = "${local.name}-data"
  vpc_id = aws_vpc.main.id
  dynamic "ingress" {
    for_each = [5432, 6379, 7687]
    content {
      from_port       = ingress.value
      to_port         = ingress.value
      protocol        = "tcp"
      security_groups = [aws_security_group.app.id]
    }
  }
}

resource "aws_db_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_db_instance" "postgres" {
  identifier             = local.name
  engine                 = "postgres"
  engine_version         = "17"
  instance_class         = "db.t4g.micro"
  allocated_storage      = 20
  storage_encrypted      = true
  db_name                = "cortex"
  username               = "cortex_owner"
  password               = random_password.db.result
  db_subnet_group_name   = aws_db_subnet_group.main.name
  vpc_security_group_ids = [aws_security_group.data.id]
  skip_final_snapshot    = true # proof window: nothing to keep
  deletion_protection    = false
  # The migrate task enables pgvector (bundled with RDS) and creates the non-owner cortex_app role.
}

resource "aws_elasticache_subnet_group" "main" {
  name       = local.name
  subnet_ids = aws_subnet.private[*].id
}

resource "aws_elasticache_cluster" "redis" {
  cluster_id         = local.name
  engine             = "redis"
  node_type          = "cache.t4g.micro"
  num_cache_nodes    = 1 # non-cluster mode, as Celery's Redis broker requires
  subnet_group_name  = aws_elasticache_subnet_group.main.name
  security_group_ids = [aws_security_group.data.id]
}

data "aws_ssm_parameter" "al2023_arm" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "neo4j" {
  ami                    = data.aws_ssm_parameter.al2023_arm.value
  instance_type          = "t4g.small"
  subnet_id              = aws_subnet.private[0].id
  vpc_security_group_ids = [aws_security_group.data.id]
  metadata_options { http_tokens = "required" }
  root_block_device {
    volume_size = 20
    encrypted   = true
  }
  # No internet route: the image comes through an ECR pull-through cache (create it before the window).
  user_data = <<-EOT
    #!/bin/bash
    dnf install -y docker && systemctl enable --now docker
    docker run -d --restart always -p 7687:7687 -e NEO4J_AUTH=neo4j/${random_password.db.result} \
      -e NEO4J_server_memory_heap_max__size=768m -v /data:/data \
      ${data.aws_caller_identity.me.account_id}.dkr.ecr.${var.region}.amazonaws.com/docker-hub/library/neo4j:2026.10.2
  EOT
  tags      = { Name = "${local.name}-neo4j" }
}

data "aws_caller_identity" "me" {}

resource "aws_s3_bucket" "documents" {
  bucket_prefix = "${local.name}-documents-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "documents" {
  bucket                  = aws_s3_bucket.documents.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_cors_configuration" "documents" {
  bucket = aws_s3_bucket.documents.id
  cors_rule {
    allowed_methods = ["PUT"] # browser uploads straight to S3 with presigned URLs
    allowed_origins = ["https://${aws_cloudfront_distribution.ui.domain_name}"]
    allowed_headers = ["Content-Type"]
    max_age_seconds = 600
  }
}
