# Glossary: ReplicationController

A (deprecated) API object that manages a replicated application.

A workload management object
that manages a replicated application, ensuring that
a specific number of instances of a Pod are running.

The control plane ensures that the defined number of Pods are running, even if some
Pods fail, if you delete Pods manually, or if too many are started by mistake.

**Note:** 
ReplicationController is deprecated. See
Deployment, which is similar.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/replication-controller.md -->
