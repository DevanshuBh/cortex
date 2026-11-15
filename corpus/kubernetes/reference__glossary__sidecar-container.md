# Glossary: Sidecar Container

An auxiliary container that stays running throughout the lifecycle of a Pod.

One or more containers that are typically started before any app containers run.

 

Sidecar containers are like regular app containers, but with a different purpose: the sidecar provides a Pod-local service to the main app container.
Unlike init containers, sidecar containers
continue running after Pod startup.

Read [Sidecar containers](/docs/concepts/workloads/pods/sidecar-containers/) for more information.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/sidecar-container.md -->
