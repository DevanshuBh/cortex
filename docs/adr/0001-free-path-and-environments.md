# ADR 0001 — Build and run for ₹0: laptop, Oracle Always Free, short AWS proof windows

Status: accepted · 2026-11-14

## Context
CORTEX is a portfolio project; it must cost nothing to build, run and demonstrate, yet show production practice.

## Decision
- **Development and evaluation** on the laptop with Docker Compose (RTX 4060 Ti 8 GB for local models).
- **Always-on demo**: k3s on an Oracle Cloud Always Free Ampere A1 VM (manifests in `deploy/k8s`), multi-arch images
  from GitHub Actions, HTTPS through a free DuckDNS name; the static UI on GitHub Pages / Cloudflare Pages in demo mode.
- **AWS**: Terraform in `deploy/terraform/aws`, applied only for a short proof window on Free plan credits, then destroyed.
- Paid managed services are replaced by self-hosted equivalents behind the same interfaces (S3 API → SeaweedFS,
  Cognito → Keycloak, Bedrock → Ollama, CloudWatch → Prometheus/Grafana/Jaeger, Secrets Manager → SOPS + age).

## Consequences
The code paths stay identical (S3 API, OIDC, OTLP, `ModelClient`); only configuration changes per environment.
Costs shown in the product are *notional* (reference list prices) and always labelled so.
