variable "kubeconfig_path" {
  type      = string
  sensitive = true
  ephemeral = true
}
provider "helm" {
  kubernetes = { config_path = var.kubeconfig_path }
}
locals {
  pool   = yamldecode(file("${path.module}/../../../config/environments/kubernetes/homelab-ci/pool-values.yaml"))
  config = "${path.module}/../../../config/environments/kubernetes/homelab-ci"
}
