# ECS Fargate: api behind an ALB, a worker, and the Coder sandbox as a one-off task per job.
resource "aws_ecs_cluster" "main" {
  name = local.name
  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

resource "aws_cloudwatch_log_group" "app" {
  name              = "/cortex/app"
  retention_in_days = 7
}

resource "aws_cloudwatch_log_group" "sandbox" {
  name              = "/cortex/sandbox"
  retention_in_days = 3
}

# ---- IAM: execution role (pull + logs), worker task role (S3 + Bedrock), and NO role for the sandbox -----------
data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-execution"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

resource "aws_iam_role_policy_attachment" "execution" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

resource "aws_iam_role" "app" {
  name               = "${local.name}-app"
  assume_role_policy = data.aws_iam_policy_document.ecs_assume.json
}

data "aws_iam_policy_document" "app" {
  statement {
    sid       = "Documents"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.documents.arn}/*"]
  }
  statement {
    sid       = "Models" # Bedrock through the task role: no stored API key anywhere (guide step 6.3)
    actions   = ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream", "bedrock:Converse", "bedrock:ConverseStream"]
    resources = ["arn:aws:bedrock:${var.region}::foundation-model/*", "arn:aws:bedrock:*:${data.aws_caller_identity.me.account_id}:inference-profile/*"]
  }
  statement {
    sid       = "RunSandbox"
    actions   = ["ecs:RunTask"]
    resources = [aws_ecs_task_definition.sandbox.arn_without_revision]
  }
  statement {
    sid       = "PassOnlyExecutionRole"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.execution.arn]
  }
  statement {
    sid       = "ReadSandboxOutput"
    actions   = ["logs:GetLogEvents", "ecs:DescribeTasks"]
    resources = ["*"]
  }
}

resource "aws_iam_role_policy" "app" {
  role   = aws_iam_role.app.id
  policy = data.aws_iam_policy_document.app.json
}

# ---- load balancer -------------------------------------------------------------------------------------------
resource "aws_security_group" "alb" {
  name   = "${local.name}-alb"
  vpc_id = aws_vpc.main.id
  ingress {
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [aws_vpc.main.cidr_block]
  }
}

resource "aws_lb" "api" {
  name               = local.name
  load_balancer_type = "application"
  subnets            = aws_subnet.public[*].id
  security_groups    = [aws_security_group.alb.id]
  idle_timeout       = 120 # above the longest gap between SSE keep-alives (15 s) with margin
}

resource "aws_lb_target_group" "api" {
  name        = "${local.name}-api"
  port        = 8000
  protocol    = "HTTP"
  vpc_id      = aws_vpc.main.id
  target_type = "ip"
  health_check { path = "/readyz" }
}

resource "aws_lb_listener" "http" {
  load_balancer_arn = aws_lb.api.arn
  port              = 80
  protocol          = "HTTP"
  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api.arn
  }
}

# ---- task definitions ----------------------------------------------------------------------------------------
locals {
  app_env = [
    { name = "CORTEX_ENV", value = "staging" },
    { name = "CORTEX_DATABASE_URL", value = "postgresql+psycopg://cortex_app:${random_password.db.result}@${aws_db_instance.postgres.address}:5432/cortex" },
    { name = "CORTEX_MIGRATION_DATABASE_URL", value = "postgresql+psycopg://cortex_owner:${random_password.db.result}@${aws_db_instance.postgres.address}:5432/cortex" },
    { name = "CORTEX_REDIS_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/0" },
    { name = "CORTEX_BROKER_URL", value = "redis://${aws_elasticache_cluster.redis.cache_nodes[0].address}:6379/1" },
    { name = "CORTEX_NEO4J_URI", value = "bolt://${aws_instance.neo4j.private_ip}:7687" },
    { name = "CORTEX_NEO4J_PASSWORD", value = random_password.db.result },
    { name = "CORTEX_S3_ENDPOINT_URL", value = "" },
    { name = "CORTEX_S3_PUBLIC_ENDPOINT_URL", value = "" },
    { name = "CORTEX_S3_BUCKET", value = aws_s3_bucket.documents.bucket },
    { name = "CORTEX_S3_REGION", value = var.region },
    { name = "CORTEX_MODEL_PROVIDER", value = "bedrock" },
    { name = "CORTEX_BEDROCK_REGION", value = var.region },
    { name = "CORTEX_BEDROCK_MODEL_SMALL", value = var.bedrock_model_small },
    { name = "CORTEX_BEDROCK_MODEL_LARGE", value = var.bedrock_model_large },
  ]
  log_config = {
    logDriver = "awslogs"
    options   = { awslogs-group = aws_cloudwatch_log_group.app.name, awslogs-region = var.region, awslogs-stream-prefix = "app" }
  }
}

resource "aws_ecs_task_definition" "api" {
  family                   = "${local.name}-api"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.app.arn
  container_definitions = jsonencode([{
    name                   = "api"
    image                  = "${var.image_repo}/cortex-backend:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    portMappings           = [{ containerPort = 8000 }]
    environment            = local.app_env
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    logConfiguration       = local.log_config
  }])
  volume { name = "tmp" }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.name}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 1024
  memory                   = 3072
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  execution_role_arn = aws_iam_role.execution.arn
  task_role_arn      = aws_iam_role.app.arn
  container_definitions = jsonencode([{
    name                   = "worker"
    image                  = "${var.image_repo}/cortex-backend:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    command                = ["sh", "-c", "mkdir -p /tmp/prometheus && exec celery -A cortex.worker.app worker -Q ask,ingest -c 2 --prefetch-multiplier=1"]
    environment            = concat(local.app_env, [{ name = "PROMETHEUS_MULTIPROC_DIR", value = "/tmp/prometheus" }])
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    stopTimeout            = 120
    logConfiguration       = local.log_config
  }])
  volume { name = "tmp" }
}

# Sandbox: no task role at all, read-only root, non-root user, hard stop. Code arrives through the RunTask
# container override and output leaves through CloudWatch Logs (both via VPC endpoints — the subnet has no route out).
resource "aws_ecs_task_definition" "sandbox" {
  family                   = "${local.name}-sandbox"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 256
  memory                   = 512
  runtime_platform {
    cpu_architecture        = "ARM64"
    operating_system_family = "LINUX"
  }
  execution_role_arn = aws_iam_role.execution.arn
  container_definitions = jsonencode([{
    name                   = "sandbox"
    image                  = "${var.image_repo}/cortex-sandbox-image:${var.image_tag}"
    essential              = true
    readonlyRootFilesystem = true
    user                   = "65534:65534"
    stopTimeout            = 2
    linuxParameters        = { capabilities = { drop = ["ALL"] }, initProcessEnabled = true }
    mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options   = { awslogs-group = aws_cloudwatch_log_group.sandbox.name, awslogs-region = var.region, awslogs-stream-prefix = "job" }
    }
  }])
  volume { name = "tmp" }
}

# Egress only to the VPC endpoints (ECR API/DKR, Logs) and the S3 gateway prefix list for image layers.
# With no egress at all the task could not even pull its image (Fargate platform 1.4+ uses the task's ENI).
resource "aws_security_group" "sandbox" {
  name   = "${local.name}-sandbox"
  vpc_id = aws_vpc.main.id
  egress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.endpoints.id]
  }
  egress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    prefix_list_ids = [aws_vpc_endpoint.s3.prefix_list_id]
  }
}

resource "aws_ecs_service" "api" {
  name            = "api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.app.id]
  }
  load_balancer {
    target_group_arn = aws_lb_target_group.api.arn
    container_name   = "api"
    container_port   = 8000
  }
  depends_on = [aws_lb_listener.http]
}

resource "aws_ecs_service" "worker" {
  name            = "worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = 1
  launch_type     = "FARGATE"
  network_configuration {
    subnets         = aws_subnet.private[*].id
    security_groups = [aws_security_group.app.id]
  }
}

# Scale workers on queue depth, published by the API as a custom CloudWatch metric (via ADOT in the window).
resource "aws_appautoscaling_target" "worker" {
  service_namespace  = "ecs"
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  min_capacity       = 1
  max_capacity       = 3
}

resource "aws_appautoscaling_policy" "worker_queue" {
  name               = "queue-depth"
  service_namespace  = aws_appautoscaling_target.worker.service_namespace
  resource_id        = aws_appautoscaling_target.worker.resource_id
  scalable_dimension = aws_appautoscaling_target.worker.scalable_dimension
  policy_type        = "TargetTrackingScaling"
  target_tracking_scaling_policy_configuration {
    target_value = 4
    customized_metric_specification {
      metric_name = "cortex_queue_depth"
      namespace   = "CORTEX"
      statistic   = "Average"
      dimensions {
        name  = "queue"
        value = "ask"
      }
    }
  }
}

output "sandbox_run_task" {
  value = {
    cluster         = aws_ecs_cluster.main.name
    task_definition = aws_ecs_task_definition.sandbox.family
    subnet          = aws_subnet.sandbox.id
    security_group  = aws_security_group.sandbox.id
  }
}
