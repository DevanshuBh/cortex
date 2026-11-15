# Glossary: EndpointSlice

EndpointSlices track the IP addresses of Pods for Services.

EndpointSlices track the IP addresses of backend endpoints.
EndpointSlices are normally associated with a
Service and the backend endpoints typically represent
Pods.

One Service can be backed by multiple Pods. Kubernetes represents the backing endpoints of a Service
with a set of EndpointSlices that are associated with that Service.
The backing endpoints are usually, but not always, pods running in the cluster.

The control plane usually manages EndpointSlices for you automatically. However,
EndpointSlices can be defined manually for Services without
selectors specified.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/endpoint-slice.md -->
