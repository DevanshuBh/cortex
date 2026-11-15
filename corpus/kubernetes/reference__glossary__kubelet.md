# Glossary: Kubelet

An agent that runs on each node in the cluster. It makes sure that containers are running in a pod.

An agent that runs on each node in the cluster. It makes sure that containers are running in a Pod.

The [kubelet](/docs/reference/command-line-tools-reference/kubelet/) takes a set of PodSpecs that 
are provided through various mechanisms and ensures that the containers described in those 
PodSpecs are running and healthy. The kubelet doesn't manage containers which were not created by 
Kubernetes.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/kubelet.md -->
