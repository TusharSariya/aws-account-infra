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
resource "helm_release" "ollama" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-models"] }
  name       = "ollama"
  namespace  = "homelab-models"
  chart      = "${path.module}/../../../charts/homelab-ollama"
  values = [file("${local.config}/ollama-values.yaml"), yamlencode({
    chartRevision = sha256(join("", [for file in sort(tolist(fileset("${path.module}/../../../charts/homelab-ollama", "**"))) : filesha256("${path.module}/../../../charts/homelab-ollama/${file}")]))
  })]
  wait        = true
  timeout     = 900
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "odysseus" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-models"] }
  name       = "odysseus"
  namespace  = "homelab-models"
  chart      = "${path.module}/../../../charts/homelab-odysseus"
  values = [file("${local.config}/workspace-values.yaml"), yamlencode({
    chartRevision = sha256(join("", [for file in sort(tolist(fileset("${path.module}/../../../charts/homelab-odysseus", "**"))) : filesha256("${path.module}/../../../charts/homelab-odysseus/${file}")]))
  })]
  wait        = true
  timeout     = 900
  max_history = 5
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "capacity" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "kube-system"] }
  name       = "homelab-capacity"
  namespace  = "kube-system"
  chart      = "${path.module}/../../../charts/homelab-capacity"
  values = [file("${local.config}/capacity-values.yaml"), yamlencode({
    config        = { cacheProjects = jsondecode(file("${local.config}/../homelab-ci/cache-storage.json")) }
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

resource "helm_release" "ai" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-models"] }
  name       = "homelab-ai"
  namespace  = "homelab-models"
  chart      = "${path.module}/../../../charts/homelab-ai"
  values = [file("${local.config}/ai-values.yaml"), yamlencode({
    recoveryCode = file("${path.module}/../../../apps/platform/recovery/archive.py")
    migrationCode = merge(
      { for f in fileset("${path.module}/../../../apps/platform/storage", "*.py") : f => file("${path.module}/../../../apps/platform/storage/${f}") },
      { "reset.py" = file("${path.module}/../../../apps/platform/migration/reset.py") }
    )
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-ai", "**"))) : filesha256("${path.module}/../../../charts/homelab-ai/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.capacity, helm_release.ollama, helm_release.odysseus]
  lifecycle {
    prevent_destroy = true
  }
}
