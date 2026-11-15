# Glossary: Secret

Stores sensitive information, such as passwords, OAuth tokens, and ssh keys.

Stores sensitive information, such as passwords, OAuth tokens, and SSH keys.

Secrets give you more control over how sensitive information is used and reduces
the risk of accidental exposure. Secret values are encoded as base64 strings and
are stored unencrypted by default, but can be configured to be
[encrypted at rest](/docs/tasks/administer-cluster/encrypt-data/#ensure-all-secrets-are-encrypted).

A Pod can reference the Secret in
a variety of ways, such as in a volume mount or as an environment variable.
Secrets are designed for confidential data and
[ConfigMaps](/docs/tasks/configure-pod-container/configure-pod-configmap/) are
designed for non-confidential data.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/secret.md -->
