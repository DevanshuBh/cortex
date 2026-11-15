# Glossary: Mixed Version Proxy (MVP)

Feature that lets a kube-apiserver proxy a resource request to a different peer API server.

Feature to let a kube-apiserver proxy a resource request to a different peer API server.

When a cluster has multiple API servers running different versions of Kubernetes, this
feature enables resource
requests to be served by the correct API server.

MVP is disabled by default and can be activated by enabling
the [feature gate](/docs/reference/command-line-tools-reference/feature-gates/) named `UnknownVersionInteroperabilityProxy` when 
the API Server is started.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/mixed-version-proxy.md -->
