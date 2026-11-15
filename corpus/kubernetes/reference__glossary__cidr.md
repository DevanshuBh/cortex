# Glossary: CIDR

CIDR is a notation for describing blocks of IP addresses and is used heavily in various networking configurations.

CIDR (Classless Inter-Domain Routing) is a notation for describing blocks of IP addresses and is used heavily in various networking configurations.

In the context of Kubernetes, each Node is assigned a range of IP addresses through the start address and a subnet mask using CIDR. This allows Nodes to assign each Pod a unique IP address. Although originally a concept for IPv4, CIDR has also been expanded to include IPv6.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/cidr.md -->
