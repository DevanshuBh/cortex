# Glossary: Control Plane

The container orchestration layer that exposes the API and interfaces to define, deploy, and manage the lifecycle of containers.

  
 
 This layer is composed by many different components, such as (but not restricted to):

 * etcd
 * API Server
 * Scheduler
 * Controller Manager
 * Cloud Controller Manager

 These components can be run as traditional operating system services (daemons) or as containers. The hosts running these components were historically called masters.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/control-plane.md -->
