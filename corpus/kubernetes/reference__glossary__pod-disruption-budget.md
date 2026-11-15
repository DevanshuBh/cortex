# Glossary: Pod Disruption Budget

An object that limits the number of Pods of a replicated application that are down simultaneously from voluntary disruptions.

A [Pod Disruption Budget](/docs/concepts/workloads/pods/disruptions/) allows an 
 application owner to create an object for a replicated application, that ensures 
 a certain number or percentage of Pods
 with an assigned label will not be voluntarily evicted at any point in time.

 

Involuntary disruptions cannot be prevented by PDBs; however they 
do count against the budget.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/pod-disruption-budget.md -->
