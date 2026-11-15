# Glossary: ResourceSlice

Represents one or more infrastructure resources, like devices, in a pool of

Represents one or more infrastructure resources, such as
devices, that are attached to
nodes. Drivers create and manage ResourceSlices in the cluster. ResourceSlices
are used for
[dynamic resource allocation (DRA)](/docs/concepts/resource-management/dynamic-resource-allocation/).

When a ResourceClaim is
created, Kubernetes uses ResourceSlices to find nodes that have access to
resources that can satisfy the claim. Kubernetes allocates resources to the
ResourceClaim and schedules the Pod onto a node that can access the resources.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/resourceslice.md -->
