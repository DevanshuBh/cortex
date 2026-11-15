# Glossary: Group Version Resource

The API group, API version and name of a Kubernetes API.

Means of representing specific Kubernetes APIs uniquely.

Group Version Resources (GVRs) specify the API group, API version, and _resource_ (name for the object kind as it appears in the URI) associated with accessing a particular id of object in Kubernetes.
GVRs let you define and distinguish different Kubernetes objects, and to specify a way of accessing
objects that is stable even as APIs change.

In this usage, _resource_ refers to an HTTP resource. Because some APIs are namespaced, a GVR may
not refer to a specific API resource.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/group-version-resource.md -->
