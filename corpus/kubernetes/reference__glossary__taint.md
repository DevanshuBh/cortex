# Glossary: Taint

A core object consisting of three required properties: key, value, and effect. Taints prevent the scheduling of pods on nodes or node groups.

A core object consisting of three required properties: key, value, and effect. Taints prevent the scheduling of Pods on nodes or node groups.

Taints and tolerations work together to ensure that pods are not scheduled onto inappropriate nodes. One or more taints are applied to a node. A node should only schedule a Pod with the matching tolerations for the configured taints.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/taint.md -->
