# Glossary: Garbage Collection

A collective term for the various mechanisms Kubernetes uses to clean up cluster

Garbage collection is a collective term for the various mechanisms Kubernetes uses to clean up
cluster resources. 

Kubernetes uses garbage collection to clean up resources like
[unused containers and images](/docs/concepts/architecture/garbage-collection/#containers-images),
[failed Pods](/docs/concepts/workloads/pods/pod-lifecycle/#pod-garbage-collection),
[objects owned by the targeted resource](/docs/concepts/overview/working-with-objects/owners-dependents/),
[completed Jobs](/docs/concepts/workloads/controllers/ttlafterfinished/), and resources
that have expired or failed.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/garbage-collection.md -->
