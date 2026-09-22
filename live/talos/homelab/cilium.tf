variable "kubeconfig_path" {
  description = "Private, temporary kubeconfig fetched from the existing Talos control plane by CI"
  type        = string
  sensitive   = true
  ephemeral   = true
}

locals {
  cilium_values = file("${path.module}/../../../config/environments/talos/homelab/cilium-values.yaml")
}

provider "helm" {
  kubernetes = {
    config_path = var.kubeconfig_path
  }
}

# CI downloads this exact chart and verifies its committed SHA-256 before plan.
resource "helm_release" "cilium" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "kube-system"] }
  name       = "cilium"
  namespace  = "kube-system"
  chart      = "${path.module}/.terraform/cilium-1.20.1.tgz"
  version    = "1.20.1"
  values     = [local.cilium_values]

  wait    = true
  timeout = 600
  # Preserve failed-install evidence; never automatically uninstall the CNI.
  atomic          = false
  cleanup_on_fail = false
  max_history     = 5

  depends_on = [talos_machine_configuration_apply.worker, talos_machine_bootstrap.cluster]
  lifecycle {
    prevent_destroy = true
    postcondition {
      condition = try(
        yamldecode(self.values[0]).kubeProxyReplacement == false &&
        yamldecode(self.values[0]).routingMode == "tunnel" &&
        yamldecode(self.values[0]).tunnelProtocol == "vxlan" &&
        yamldecode(self.values[0]).ipam.mode == "kubernetes",
        false
      )
      error_message = "Cilium must retain kube-proxy, VXLAN and Kubernetes IPAM."
    }
  }
}
