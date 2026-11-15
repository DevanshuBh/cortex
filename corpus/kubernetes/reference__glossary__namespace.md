# Glossary: Namespace

An abstraction used by Kubernetes to support isolation of groups of resources within a single cluster.

An abstraction used by Kubernetes to support isolation of groups of API resources
within a single cluster.

 

Namespaces are used to organize objects in a cluster and provide a way to divide cluster resources. Names of resources need to be unique within a namespace, but not across namespaces. Namespace-based scoping is applicable only for namespaced resources _(for example: Pods, Deployments, Services)_ and not for cluster-wide resources _(for example: StorageClasses, Nodes, PersistentVolumes)_.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/namespace.md -->
