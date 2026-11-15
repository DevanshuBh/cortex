# Glossary: Storage Class

A StorageClass provides a way for administrators to describe different available storage types.

 

StorageClasses can map to quality-of-service levels, backup policies, or to arbitrary policies determined by cluster administrators. Each StorageClass contains the fields `provisioner`, `parameters`, and `reclaimPolicy`, which are used when a Persistent Volume belonging to the class needs to be dynamically provisioned. Users can request a particular class using the name of a StorageClass object.

<!-- source: https://github.com/kubernetes/website/blob/109ff5a76323d1c28a1cc6d5c41b139c8e2a22b3/content/en/docs/reference/glossary/storage-class.md -->
