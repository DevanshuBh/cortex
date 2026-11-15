# Glossary: Ephemeral Container

A type of container that you can temporarily run inside a Pod.

A container type that you can temporarily run inside a pod.

If you want to investigate a Pod that's running with problems, you can add an ephemeral container to that Pod and carry out diagnostics.
Ephemeral containers have no resource or scheduling guarantees,
and you should not use them to run any part of the workload itself.

Ephemeral containers are not supported by static pods.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/ephemeral-container.md -->
