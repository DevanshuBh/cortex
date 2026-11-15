# ADR 0010 — Front end as a static export (Next.js 16), not a Next.js server

Status: accepted · 2026-11-15

## Decision
The research workspace is a Next.js 16 / React 19 static export (`output: "export"`). It talks to the API with
tokens kept in memory (OIDC Authorization Code + PKCE via Keycloak), streams answers over SSE with fetch, and is
hosted on any static host (GitHub Pages / Cloudflare Pages free; S3 + CloudFront on AWS).

## Why
No server to run, patch or scale; global caching; the API is already the only back end. Static hosting is free.

## Trade-offs
No server components or server-side auth; every page is client-rendered after login (acceptable for an
authenticated workspace). A demo build swaps the API for Mock Service Worker replaying recorded responses, so the
public demo needs no back end.

## Deviation from the guide
Components are written in the shadcn/ui style (owned Tailwind components, design tokens in `@theme`), not generated
by the shadcn CLI or built on Radix; accessibility is proven by axe + Playwright instead (zero WCAG 2.2 AA
violations on all journeys, desktop and phone).
