# Glossary: Dynamic Resource Allocation

A Kubernetes feature for requesting and sharing resources, like hardware

A Kubernetes feature that lets you request and share resources among Pods.
These resources are often attached
devices like hardware
accelerators.

With DRA, device drivers and cluster admins define device _classes_ that are
available to _claim_ in workloads. Kubernetes allocates matching devices to
specific claims and places the corresponding Pods on nodes that can access the
allocated devices.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/dra.md -->
