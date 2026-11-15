# Glossary: ResourceClaimTemplate

Defines a template for Kubernetes to create ResourceClaims. Used to provide

Defines a template that Kubernetes uses to create
ResourceClaims.
ResourceClaimTemplates are used in
[dynamic resource allocation (DRA)](/docs/concepts/resource-management/dynamic-resource-allocation/)
to provide _per-Pod or per-PodGroup access to separate, similar resources_.

When a ResourceClaimTemplate is referenced in a workload specification,
Kubernetes automatically creates ResourceClaim objects based on the template.
Each ResourceClaim is bound to a specific Pod or PodGroup. When the Pod
terminates or the PodGroup is deleted, Kubernetes deletes the corresponding
ResourceClaim. PodGroup ResourceClaimTemplates require the
[`DRAWorkloadResourceClaims`](/docs/reference/command-line-tools-reference/feature-gates/#DRAWorkloadResourceClaims)
feature to be enabled.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/resourceclaimtemplate.md -->
