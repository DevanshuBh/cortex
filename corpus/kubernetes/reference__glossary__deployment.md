# Glossary: Deployment

Manages a replicated application on your cluster.

An API object that manages a replicated application, typically by running Pods with no local state.

 

Each replica is represented by a pod, and the Pods are distributed among the 
nodes of a cluster.
For workloads that do require local state, consider using a StatefulSet.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/deployment.md -->
