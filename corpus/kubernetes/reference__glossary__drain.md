# Glossary: Drain

Safely evicts Pods from a Node to prepare for maintenance or removal.

The process of safely evicting Pods from a Node to prepare it for maintenance or removal from a cluster.

The `kubectl drain` command is used to mark a Node as going out of service. 
When executed, it evicts all Pods from the Node. 
If an eviction request is temporarily rejected, `kubectl drain` retries until all Pods are terminated or a configurable timeout is reached.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/drain.md -->
