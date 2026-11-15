# Glossary: ReplicaSet

ReplicaSet ensures that a specified number of Pod replicas are running at one time

A ReplicaSet (aims to) maintain a set of replica Pods running at any given time.

Workload objects such as deployment make use of ReplicaSets
to ensure that the configured number of Pods are
running in your cluster, based on the spec of that ReplicaSet.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/replica-set.md -->
