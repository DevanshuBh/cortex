# Glossary: QoS Class

QoS Class (Quality of Service Class) provides a way for Kubernetes to classify pods within the cluster into several classes and make decisions about scheduling and eviction.

QoS Class (Quality of Service Class) provides a way for Kubernetes to classify Pods within the cluster into several classes and make decisions about scheduling and eviction.

 
QoS Class of a Pod is set at creation time based on its infrastructure resource
requests and limits settings. QoS classes are used to make decisions about Pods scheduling and eviction.
Kubernetes can assign one of the following  QoS classes to a Pod: `Guaranteed`, `Burstable` or `BestEffort`.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/qos-class.md -->
