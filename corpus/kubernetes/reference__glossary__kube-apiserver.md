# Glossary: API server

Control plane component that serves the Kubernetes API.

The API server is a component of the Kubernetes
control plane that exposes the Kubernetes API.
The API server is the front end for the Kubernetes control plane.

The main implementation of a Kubernetes API server is [kube-apiserver](/docs/reference/generated/kube-apiserver/).
kube-apiserver is designed to scale horizontally&mdash;that is, it scales by deploying more instances.
You can run several instances of kube-apiserver and balance traffic between those instances.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/kube-apiserver.md -->
