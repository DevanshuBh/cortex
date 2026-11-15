# Glossary: Common Expression Language

An expression language that's designed to be safe for executing user code.

A general-purpose expression language that's designed to be fast, portable, and
safe to execute.

In Kubernetes, CEL can be used to run queries and perform fine-grained
filtering. For example, you can use CEL expressions with
[dynamic admission control](/docs/reference/access-authn-authz/extensible-admission-controllers/)
to filter for specific fields in requests, and with
[dynamic resource allocation (DRA)](/docs/concepts/resource-management/dynamic-resource-allocation/)
to select resources based on specific attributes.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/cel.md -->
