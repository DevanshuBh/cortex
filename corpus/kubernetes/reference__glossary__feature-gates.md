# Glossary: Feature gate

A way to control whether or not a particular Kubernetes feature is enabled.

Feature gates are a set of keys (opaque string values) that you can use to control which
Kubernetes features are enabled in your cluster.

You can turn these features on or off using the `--feature-gates` command line flag on each Kubernetes component.
Each Kubernetes component lets you enable or disable a set of feature gates that are relevant to that component.
The Kubernetes documentation lists all current 
[feature gates](/docs/reference/command-line-tools-reference/feature-gates/) and what they control.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/feature-gates.md -->
