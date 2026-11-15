# Glossary: Condition

A condition represents the current state of a Kubernetes resource, providing information about whether certain aspects of the resource are true.

A condition is a field in a Kubernetes resource's status that describes the current state of that resource.

Conditions provide a standardized way for Kubernetes components to communicate the status of resources. Each condition has a `type`, a `status` (True, False, or Unknown), and optional fields like `reason` and `message` that provide additional details. For example, a Pod might have conditions like `Ready`, `ContainersReady`, or `PodScheduled`.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/condition.md -->
