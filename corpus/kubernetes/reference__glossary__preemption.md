# Glossary: Preemption

Preemption logic in Kubernetes helps a pending Pod to find a suitable Node by evicting low priority Pods existing on that Node.

Preemption logic in Kubernetes helps a pending pod to find a suitable node by evicting low priority Pods existing on that Node.

If a Pod cannot be scheduled, the scheduler tries to [preempt](/docs/concepts/scheduling-eviction/pod-priority-preemption/#preemption) lower priority Pods to make scheduling of the pending Pod possible.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/preemption.md -->
