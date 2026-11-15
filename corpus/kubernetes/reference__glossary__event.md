# Glossary: Event

Kubernetes objects that describe some state change in the cluster.

A Kubernetes object that describes state changes
or notable occurrences in the cluster.

Events have a limited retention time and triggers and messages may evolve with time.
Event consumers should not rely on the timing of an event with a given reason reflecting a consistent underlying trigger,
or the continued existence of events with that reason.

Events should be treated as informative, best-effort, supplemental data.

In Kubernetes, [auditing](/docs/tasks/debug/debug-cluster/audit/) generates a different kind of
Event record (API group `audit.k8s.io`).

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/event.md -->
