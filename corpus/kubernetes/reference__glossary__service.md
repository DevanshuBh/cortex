# Glossary: Service

A way to expose an application running on a set of Pods as a network service.

A method for exposing a network application that is running as one or more
Pods in your cluster.

The set of Pods targeted by a Service is (usually) determined by a
selector. If more Pods are added or removed,
the set of Pods matching the selector will change. The Service makes sure that network traffic
can be directed to the current set of Pods for the workload.

Kubernetes Services either use IP networking (IPv4, IPv6, or both), or reference an external name in
the Domain Name System (DNS).

The Service abstraction enables other mechanisms, such as Ingress and Gateway.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/service.md -->
