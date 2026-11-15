# Glossary: user namespace

A Linux kernel feature to emulate superuser privilege for unprivileged users.

A kernel feature to emulate root. Used for "rootless containers".

User namespaces are a Linux kernel feature that allows a non-root user to
emulate superuser ("root") privileges,
for example in order to run containers without being a superuser outside the container.

User namespace is effective for mitigating damage of potential container break-out attacks.

In the context of user namespaces, the namespace is a Linux kernel feature, and not a
namespace in the Kubernetes sense
of the term.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/userns.md -->
