# Glossary: Toleration

A core object consisting of three required properties: key, value, and effect. Tolerations enable the scheduling of pods on nodes or node groups that have a matching taint.

A core object consisting of three required properties: key, value, and effect. Tolerations enable the scheduling of pods on nodes or node groups that have matching taints.

Tolerations and taints work together to ensure that pods are not scheduled onto inappropriate nodes. One or more tolerations are applied to a pod. A toleration indicates that the pod is allowed (but not required) to be scheduled on nodes or node groups with matching taints.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/toleration.md -->
