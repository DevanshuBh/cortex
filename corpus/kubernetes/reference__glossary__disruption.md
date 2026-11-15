# Glossary: Disruption

An event that leads to Pod(s) going out of service

Disruptions are events that lead to one or more
Pods going out of service.
A disruption has consequences for workload management resources,
such as deployment, that rely on the affected
Pods.

If you, as cluster operator, destroy a Pod that belongs to an application,
Kubernetes terms that a _voluntary disruption_. If a Pod goes offline
because of a Node failure, or an outage affecting a wider failure zone,
Kubernetes terms that an _involuntary disruption_.

See [Disruptions](/docs/concepts/workloads/pods/disruptions/) for more information.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/disruption.md -->
