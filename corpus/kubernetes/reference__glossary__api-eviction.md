# Glossary: API-initiated eviction

API-initiated eviction is the process by which you use the Eviction API to create an

API-initiated eviction is the process by which you use the [Eviction API](/docs/reference/generated/kubernetes-api/v1.36/#create-eviction-pod-v1-core)
to create an `Eviction` object that triggers graceful pod termination.

You can request eviction either by directly calling the Eviction API 
using a client of the kube-apiserver, like the `kubectl drain` command. 
When an `Eviction` object is created, the API server terminates the Pod. 

API-initiated evictions respect your configured [`PodDisruptionBudgets`](/docs/tasks/run-application/configure-pdb/)
and [`terminationGracePeriodSeconds`](/docs/concepts/workloads/pods/pod-lifecycle#pod-termination).

API-initiated eviction is not the same as [node-pressure eviction](/docs/concepts/scheduling-eviction/node-pressure-eviction/).

* See [API-initiated eviction](/docs/concepts/scheduling-eviction/api-eviction/) for more information.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/api-eviction.md -->
