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

resource "helm_release" "ollama" {
  name      = "ollama"
  namespace = "homelab-models"
  chart     = "${path.module}/../../../charts/homelab-ollama"
  values = [file("${local.config}/ollama-values.yaml"), yamlencode({
    chartRevision = sha256(join("", [for file in sort(tolist(fileset("${path.module}/../../../charts/homelab-ollama", "**"))) : filesha256("${path.module}/../../../charts/homelab-ollama/${file}")]))
  })]
  wait        = true
  timeout     = 900
  max_history = 5
  depends_on  = [helm_release.tailscale_operator]
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "odysseus" {
  name      = "odysseus"
  namespace = "homelab-models"
  chart     = "${path.module}/../../../charts/homelab-odysseus"
  values = [file("${local.config}/workspace-values.yaml"), yamlencode({
    chartRevision = sha256(join("", [for file in sort(tolist(fileset("${path.module}/../../../charts/homelab-odysseus", "**"))) : filesha256("${path.module}/../../../charts/homelab-odysseus/${file}")]))
  })]
  wait        = true
  timeout     = 900
  max_history = 5
  depends_on  = [helm_release.tailscale_operator]
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "capacity" {
  name      = "homelab-capacity"
  namespace = "kube-system"
  chart     = "${path.module}/../../../charts/homelab-capacity"
  values = [file("${local.config}/capacity-values.yaml"), yamlencode({
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-capacity", "**"))) : filesha256("${path.module}/../../../charts/homelab-capacity/${f}")]))
    code          = { for f in fileset("${path.module}/../../../apps/platform/storage", "*.py") : f => file("${path.module}/../../../apps/platform/storage/${f}") }
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}
