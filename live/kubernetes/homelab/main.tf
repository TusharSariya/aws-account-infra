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
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "tailscale"] }
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
  set         = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender  = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-services"] }
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
  depends_on  = [helm_release.tailscale_operator]
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
  depends_on  = [helm_release.tailscale_operator]
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

resource "helm_release" "lifecycle" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-platform"] }
  name       = "homelab-lifecycle"
  namespace  = "homelab-platform"
  chart      = "${path.module}/../../../charts/homelab-lifecycle"
  values = [file("${local.config}/lifecycle-values.yaml"), yamlencode({
    code = merge(
      { for f in fileset("${path.module}/../../../apps/platform/storage", "*.py") : f => file("${path.module}/../../../apps/platform/storage/${f}") },
      { for f in fileset("${path.module}/../../../apps/platform/lifecycle", "*.py") : f => file("${path.module}/../../../apps/platform/lifecycle/${f}") }
    )
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-lifecycle", "**"))) : filesha256("${path.module}/../../../charts/homelab-lifecycle/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.ai]
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "argo" {
  set              = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender       = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-jobs"] }
  name             = "argo-workflows"
  namespace        = "homelab-jobs"
  create_namespace = true
  chart            = "${path.module}/.terraform/argo-workflows-2.0.5.tgz"
  version          = "2.0.5"
  values           = [file("${local.config}/argo-values.yaml")]
  wait             = true
  timeout          = 600
  max_history      = 5
  depends_on       = [helm_release.lifecycle]
  lifecycle {
    prevent_destroy = true
  }
}

resource "helm_release" "jobs" {
  set        = [{ name = "mainPlacementRevision", value = local.main_placement_revision }]
  postrender = { binary_path = "${path.module}/../../../kubernetes/platform/main/placement/helm-post-renderer.py", args = ["--namespace", "homelab-jobs"] }
  name       = "homelab-jobs"
  namespace  = "homelab-jobs"
  chart      = "${path.module}/../../../charts/homelab-jobs"
  values = [yamlencode({
    code          = { for f in fileset("${path.module}/../../../apps/platform/jobs", "*.py") : f => file("${path.module}/../../../apps/platform/jobs/${f}") }
    chartRevision = sha256(join("", [for f in sort(tolist(fileset("${path.module}/../../../charts/homelab-jobs", "**"))) : filesha256("${path.module}/../../../charts/homelab-jobs/${f}")]))
  })]
  wait        = true
  timeout     = 300
  max_history = 5
  depends_on  = [helm_release.argo]
  lifecycle {
    prevent_destroy = true
  }
}
