variable "kubeconfig_path" {
  description = "Private ephemeral kubeconfig for the existing homelab"
  type        = string
  sensitive   = true
  ephemeral   = true
}
provider "helm" {
  kubernetes = { config_path = var.kubeconfig_path }
}
locals {
  config = "${path.module}/../../../config/environments/kubernetes/homelab"
}
resource "helm_release" "tailscale_operator" {
  name        = "tailscale-operator"
  namespace   = "tailscale"
  chart       = "${path.module}/.terraform/tailscale-operator-1.102.3.tgz"
  version     = "1.102.3"
  values      = [file("${local.config}/operator-values.yaml")]
  wait        = true
  timeout     = 600
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}
resource "helm_release" "pihole" {
  name        = "pihole"
  namespace   = "homelab-services"
  chart       = "${path.module}/.terraform/pihole-2.38.0.tgz"
  version     = "2.38.0"
  values      = [file("${local.config}/pihole-values.yaml")]
  wait        = true
  timeout     = 600
  max_history = 5
  depends_on  = [helm_release.tailscale_operator]
}
