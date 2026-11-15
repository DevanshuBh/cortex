# Oracle Cloud Always Free: one Ampere A1 VM (2 OCPU, 12 GB) running k3s, gVisor, KEDA and cert-manager.
#   terraform init && terraform apply -var-file=free.tfvars
terraform {
  required_version = ">= 1.9"
  required_providers {
    oci = { source = "oracle/oci", version = "~> 7.0" }
  }
}

provider "oci" {
  region = var.region
}

variable "region" { type = string }
variable "compartment_ocid" { type = string }
variable "ssh_public_key" { type = string }
variable "admin_cidr" {
  type        = string
  description = "Your IP/32 — the only address allowed to reach SSH and the Kubernetes API"
}
variable "duckdns_domain" {
  type        = string
  description = "e.g. cortex-demo (for cortex-demo.duckdns.org)"
}
variable "duckdns_token" {
  type      = string
  sensitive = true
}

data "oci_identity_availability_domains" "ads" { compartment_id = var.compartment_ocid }

data "oci_core_images" "ubuntu_arm" {
  compartment_id           = var.compartment_ocid
  operating_system         = "Canonical Ubuntu"
  operating_system_version = "24.04"
  shape                    = "VM.Standard.A1.Flex"
  sort_by                  = "TIMECREATED"
  sort_order               = "DESC"
}

resource "oci_core_vcn" "cortex" {
  compartment_id = var.compartment_ocid
  cidr_blocks    = ["10.20.0.0/16"]
  display_name   = "cortex"
  dns_label      = "cortex"
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.cortex.id
  display_name   = "cortex-igw"
}

resource "oci_core_route_table" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.cortex.id
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_security_list" "public" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.cortex.id
  display_name   = "cortex-public"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }
  dynamic "ingress_security_rules" {
    for_each = { http = 80, https = 443 }
    content {
      source   = "0.0.0.0/0"
      protocol = "6"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
  dynamic "ingress_security_rules" {
    for_each = { ssh = 22, kubeapi = 6443 }
    content {
      source   = var.admin_cidr
      protocol = "6"
      tcp_options {
        min = ingress_security_rules.value
        max = ingress_security_rules.value
      }
    }
  }
}

resource "oci_core_subnet" "public" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.cortex.id
  cidr_block        = "10.20.1.0/24"
  route_table_id    = oci_core_route_table.public.id
  security_list_ids = [oci_core_security_list.public.id]
  dns_label         = "public"
}

resource "oci_core_instance" "k3s" {
  compartment_id      = var.compartment_ocid
  availability_domain = data.oci_identity_availability_domains.ads.availability_domains[0].name
  display_name        = "cortex-k3s"
  shape               = "VM.Standard.A1.Flex"
  shape_config {
    ocpus         = 2
    memory_in_gbs = 12
  }
  source_details {
    source_type             = "image"
    source_id               = data.oci_core_images.ubuntu_arm.images[0].id
    boot_volume_size_in_gbs = 100
  }
  create_vnic_details {
    subnet_id        = oci_core_subnet.public.id
    assign_public_ip = true
  }
  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data = base64encode(templatefile("${path.module}/cloud-init.yaml", {
      duckdns_domain = var.duckdns_domain
      duckdns_token  = var.duckdns_token
    }))
  }
}

output "public_ip" { value = oci_core_instance.k3s.public_ip }
output "next_steps" {
  value = "ssh ubuntu@${oci_core_instance.k3s.public_ip}; then: sops -d deploy/k8s/secrets.enc.yaml | kubectl apply -f - && kubectl apply -k deploy/k8s"
}
