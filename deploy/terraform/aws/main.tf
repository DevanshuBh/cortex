# AWS proof window (ADR 0001): apply for a day on Free plan credits, record numbers, then `terraform destroy`.
#   terraform init && terraform apply -var-file=window.tfvars
terraform {
  required_version = ">= 1.9"
  required_providers {
    aws    = { source = "hashicorp/aws", version = "~> 6.0" }
    random = { source = "hashicorp/random", version = "~> 3.6" }
  }
}

provider "aws" {
  region = var.region
  default_tags { tags = { project = "cortex", window = "proof", managed_by = "terraform" } }
}

provider "aws" {
  alias  = "us_east_1" # budgets are a global service managed from us-east-1
  region = "us-east-1"
}

variable "region" {
  type    = string
  default = "ap-south-1"
}
variable "image_tag" {
  type    = string
  default = "latest"
}
variable "image_repo" {
  type        = string
  description = "e.g. ghcr.io/devanshubh — or an ECR repository URL"
}
variable "alert_email" { type = string }
variable "monthly_budget_usd" {
  type    = number
  default = 25
}
variable "bedrock_model_small" {
  type    = string
  default = "amazon.nova-micro-v1:0"
}
variable "bedrock_model_large" {
  type    = string
  default = "amazon.nova-pro-v1:0"
}

data "aws_availability_zones" "available" { state = "available" }

locals {
  name = "cortex"
  azs  = slice(data.aws_availability_zones.available.names, 0, 2)
}

resource "random_password" "db" {
  length  = 32
  special = false
}

resource "random_password" "sandbox_token" {
  length  = 40
  special = false
}

resource "aws_budgets_budget" "monthly" {
  provider     = aws.us_east_1
  name         = "cortex-monthly"
  budget_type  = "COST"
  limit_amount = tostring(var.monthly_budget_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 50
    threshold_type             = "PERCENTAGE"
    notification_type          = "ACTUAL"
    subscriber_email_addresses = [var.alert_email]
  }
  notification {
    comparison_operator        = "GREATER_THAN"
    threshold                  = 100
    threshold_type             = "PERCENTAGE"
    notification_type          = "FORECASTED"
    subscriber_email_addresses = [var.alert_email]
  }
}

output "api_url" { value = "http://${aws_lb.api.dns_name}" }
output "ui_url" { value = "https://${aws_cloudfront_distribution.ui.domain_name}" }
output "documents_bucket" { value = aws_s3_bucket.documents.bucket }
output "reminder" { value = "Run `terraform destroy` when the window ends, then check Billing the next day." }
