# Static export in a private S3 bucket behind CloudFront (Origin Access Control) with security headers.
resource "aws_s3_bucket" "ui" {
  bucket_prefix = "${local.name}-ui-"
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "ui" {
  bucket                  = aws_s3_bucket.ui.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_cloudfront_origin_access_control" "ui" {
  name                              = "${local.name}-ui"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_cloudfront_response_headers_policy" "security" {
  name = "${local.name}-security"
  security_headers_config {
    content_security_policy {
      content_security_policy = "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' http://${aws_lb.api.dns_name} https://*.amazonaws.com; worker-src 'self' blob:; frame-ancestors 'none'; object-src 'none'; base-uri 'self'"
      override                = true
    }
    strict_transport_security {
      access_control_max_age_sec = 31536000
      include_subdomains         = true
      override                   = true
    }
    content_type_options { override = true }
    frame_options {
      frame_option = "DENY"
      override     = true
    }
    referrer_policy {
      referrer_policy = "strict-origin-when-cross-origin"
      override        = true
    }
  }
}

data "aws_cloudfront_cache_policy" "optimized" { name = "Managed-CachingOptimized" }

resource "aws_cloudfront_distribution" "ui" {
  enabled             = true
  default_root_object = "index.html"
  price_class         = "PriceClass_200" # includes India edge locations
  origin {
    domain_name              = aws_s3_bucket.ui.bucket_regional_domain_name
    origin_id                = "ui"
    origin_access_control_id = aws_cloudfront_origin_access_control.ui.id
  }
  default_cache_behavior {
    target_origin_id           = "ui"
    viewer_protocol_policy     = "redirect-to-https"
    allowed_methods            = ["GET", "HEAD"]
    cached_methods             = ["GET", "HEAD"]
    cache_policy_id            = data.aws_cloudfront_cache_policy.optimized.id
    response_headers_policy_id = aws_cloudfront_response_headers_policy.security.id
    compress                   = true
  }
  restrictions {
    geo_restriction { restriction_type = "none" }
  }
  viewer_certificate { cloudfront_default_certificate = true }
}

data "aws_iam_policy_document" "ui" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.ui.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.ui.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "ui" {
  bucket = aws_s3_bucket.ui.id
  policy = data.aws_iam_policy_document.ui.json
}

# Deploy: aws s3 sync web/out s3://<bucket> --cache-control "public,max-age=31536000,immutable" --exclude "*.html"
#         aws s3 sync web/out s3://<bucket> --exclude "*" --include "*.html" --cache-control "no-cache"
#         aws cloudfront create-invalidation --distribution-id <id> --paths "/*.html" "/"
output "ui_bucket" { value = aws_s3_bucket.ui.bucket }
output "ui_distribution_id" { value = aws_cloudfront_distribution.ui.id }
