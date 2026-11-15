# Glossary: Affinity

Rules used by the scheduler to determine where to place pods

In Kubernetes, _affinity_ is a set of rules that give hints to the scheduler about where to place pods.

There are two kinds of affinity:
* [node affinity](/docs/concepts/scheduling-eviction/assign-pod-node/#node-affinity)
* [pod-to-pod affinity](/docs/concepts/scheduling-eviction/assign-pod-node/#inter-pod-affinity-and-anti-affinity)

The rules are defined using the Kubernetes labels,
and selectors specified in pods, 
and they can be either required or preferred, depending on how strictly you want the scheduler to enforce them.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/affinity.md -->
