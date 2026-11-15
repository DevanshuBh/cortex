# Glossary: Cloud Controller Manager

Control plane component that integrates Kubernetes with third-party cloud providers.

A Kubernetes control plane component
that embeds cloud-specific control logic. The cloud controller manager lets you link your
cluster into your cloud provider's API, and separates out the components that interact
with that cloud platform from components that only interact with your cluster.

By decoupling the interoperability logic between Kubernetes and the underlying cloud
infrastructure, the cloud-controller-manager component enables cloud providers to release
features at a different pace compared to the main Kubernetes project.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/cloud-controller-manager.md -->
