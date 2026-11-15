# Glossary: Operator pattern

A specialized controller used to manage a custom resource

The [operator pattern](/docs/concepts/extend-kubernetes/operator/) is a system
design that links a controller to one or more custom
resources.

You can extend Kubernetes by adding controllers to your cluster, beyond the built-in
controllers that come as part of Kubernetes itself.

If a running application acts as a controller and has API access to carry out tasks
against a custom resource that's defined in the control plane, that's an example of
the Operator pattern.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/operator-pattern.md -->
