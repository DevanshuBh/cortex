# Glossary: App Container

A container used to run part of a workload. Compare with init container.

Application containers (or app containers) are the containers in a pod that are started after any init containers have completed.

An init container lets you separate initialization details that are important for the overall 
workload, and that don't need to keep running
once the application container has started.
If a pod doesn't have any init containers configured, all the containers in that pod are app containers.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/app-container.md -->
